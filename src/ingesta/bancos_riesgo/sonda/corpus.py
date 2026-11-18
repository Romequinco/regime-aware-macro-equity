"""Originales, texto y catálogo local con las mismas claves que el bucket S3.

Preparar el corpus no consulta la red. La subida es una operación separada y su
valor predeterminado es una simulación. No se modifica el esquema común de Fase 2.
"""

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import unicodedata
from uuid import uuid4

import pandas as pd

from .http import Original
from .parsing import chunks, extract
from .temporal import add_metrics, available_at

SCHEMA_VERSION = 'bancos-catalogo-v1'
TIPOS_DATO = frozenset({'politica_monetaria', 'estabilidad_financiera', 'informes_macro',
                        'mercados_internacionales', 'literatura'})
REGIONES = {'Fed': 'USA', 'BCE': 'Europa', 'BoE': 'Europa', 'BoJ': 'Asia',
            'PBoC (China)': 'Asia', 'RBI (India)': 'Asia', 'SNB (Suiza)': 'Europa',
            'BoC (Canadá)': 'Canada', 'BCB (Brasil)': 'Latinoamerica',
            'Banxico (México)': 'Latinoamerica', 'FMI': 'Global', 'BIS': 'Global'}
COLUMNAS = [
    'documento_id', 'version_id', 'nombre', 'url', 'tipo_dato', 'formato_original',
    'entidad', 'familia', 'region_emisora', 'mercados_objetivo', 'funcion', 'idioma', 'licencia',
    'fecha_evento', 'fecha_publicacion', 'precision_publicacion', 'publicacion_utc', 'anuncio_utc',
    'zona_fuente', 'fecha_aplicacion', 'primera_observacion_utc', 'consulta_utc',
    'evidencia_publicacion', 'version_acreditada', 'evidencia_version',
    'disponible_desde_utc', 'disponible_desde_observacion_utc',
    'apto_historico_acreditado', 'apto_desde_observacion', 'motivo_historico',
    'texto_completo', 'naturaleza_contenido', 'paginas_total', 'paginas_procesadas',
    'paginas_sin_texto', 'requiere_revision_ocr', 'estado_extraccion',
    'original_disponible', 'original_key', 'texto_key', 'documento_key', 'fragmentos_key',
    's3_original', 's3_texto', 'original_sha256', 'texto_sha256',
    'extractor_version', 'schema_version', 'ejecucion_id',
]


def _verdadero(value):
    return str(value).lower() in ('true', '1')


def _utc(value):
    if value is None or str(value).strip() in ('', 'None', 'NaT', 'nan'):
        return None
    try:
        parsed = pd.Timestamp(value)
        return None if pd.isna(parsed) or parsed.tzinfo is None else parsed.tz_convert('UTC')
    except (ValueError, TypeError):
        return None


def disponibilidad(documento, original_disponible=True):
    """Separar evidencia histórica de lo observado realmente por este recolector.

    La publicación impresa no permite retroceder una versión descargada hoy.
    Tampoco se certifica un histórico por el nombre de archivo, S3 LastModified
    o la fecha de reunión. La acreditación exige evidencia explícita adicional.
    """
    complete = (_verdadero(documento.get('texto_completo')) and bool(documento.get('texto', '').strip())
                and not _verdadero(documento.get('requiere_revision_ocr')) and original_disponible)
    historical = None
    if complete and str(documento.get('evidencia_version') or '').strip():
        try:
            historical = _utc(available_at(documento))
        except (ValueError, TypeError, KeyError):
            historical = None
    observed = _utc(documento.get('retrieved_at')) if complete else None
    # Un fichero observado antes de la fecha anunciada tampoco se adelanta al embargo.
    publication = _utc(documento.get('anuncio_utc')) or _utc(documento.get('publicacion_utc'))
    if publication is None and documento.get('precision_publicacion') == 'día':
        try:
            bound = dict(documento, texto_completo=True, version_acreditada=True)
            publication = _utc(available_at(bound))
            if publication is None:
                # Sin zona, dos días UTC cubren conservadoramente el final del día mundial.
                publication = pd.Timestamp(documento['fecha_publicacion'][:10], tz='UTC') + pd.Timedelta(days=2)
        except (ValueError, TypeError, KeyError):
            publication = None
    if observed is not None and publication is not None:
        observed = max(observed, publication)
    if historical is not None and publication is not None:
        historical = max(historical, publication)
    if not original_disponible:
        reason = 'Original no disponible en la cache; no se acredita la copia'
    elif not complete:
        reason = 'Texto parcial, vacío o pendiente de revisión OCR'
    elif historical is None:
        reason = 'Versión histórica sin evidencia; solo utilizable desde observación verificada'
    else:
        reason = 'Versión histórica con evidencia y texto completo; revisar aplicabilidad y sesión de mercado'
    return {
        'disponible_desde_utc': historical.isoformat() if historical is not None else None,
        'disponible_desde_observacion_utc': observed.isoformat() if observed is not None else None,
        'apto_historico_acreditado': historical is not None,
        'apto_desde_observacion': observed is not None,
        'motivo_historico': reason,
    }


def filtrar_catalogo(catalogo, corte_utc, modo='acreditado'):
    """Filtro previo a recuperación: el resultado no incluye documentos del futuro.

    ``acreditado`` admite versiones históricas con evidencia. ``observado`` exige
    haber observado los bytes antes del corte y sirve para evaluación desde la
    captura en adelante. No mezcla silenciosamente ambas bases temporales.
    """
    cutoff = _utc(corte_utc)
    if cutoff is None:
        raise ValueError('El corte debe ser una fecha válida con zona horaria')
    if modo not in ('acreditado', 'observado'):
        raise ValueError('Modo: acreditado u observado')
    flag = 'apto_historico_acreditado' if modo == 'acreditado' else 'apto_desde_observacion'
    column = 'disponible_desde_utc' if modo == 'acreditado' else 'disponible_desde_observacion_utc'
    dates = catalogo[column].map(_utc)
    eligible = (catalogo[flag].map(_verdadero) & catalogo['texto_completo'].map(_verdadero)
                & catalogo['original_disponible'].map(_verdadero)
                & ~catalogo['requiere_revision_ocr'].map(_verdadero)
                & dates.map(lambda value: value is not None and value <= cutoff))
    if modo == 'acreditado':
        eligible &= (catalogo['version_acreditada'].map(_verdadero)
                     & catalogo['evidencia_version'].fillna('').str.strip().ne(''))
    return catalogo.loc[eligible].copy()


def _slug(value):
    value = unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '_', value.lower()).strip('_')[:36] or 'sin_entidad'


def _identidad(doc):
    key = '\0'.join(str(doc.get(k) or '') for k in ('fuente', 'url', 'tipo'))
    return sha256(key.encode('utf-8')).hexdigest()[:20]


def _json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


def _csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, COLUMNAS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def _extension(content, formato):
    if content.startswith(b'%PDF'):
        return 'pdf'
    if 'html' in str(formato).lower():
        return 'html'
    if 'json' in str(formato).lower():
        return 'json'
    if str(formato).lower() in ('xlsx', 'xls', 'csv'):
        return str(formato).lower()
    return 'zip' if content.startswith(b'PK') else 'bin'


def cargar_muestras_guardadas(sonda, reextraer_pdf=True):
    """Recuperar solo familias del inventario activo, sin tocar las fuentes web.

    Reextraer procesa el PDF local completo. No acredita fechas/versiones que
    antes fueran desconocidas ni sobrescribe las muestras antiguas en local/.
    """
    inventory = {(s['apartado'], s['fuente'], s['tipo']): s for s in sonda.inventory}
    for section in sorted({s['apartado'] for s in sonda.inventory}):
        path = sonda.corpus / 'local' / 'sonda' / f'apartado_{section:02}.jsonl'
        if not path.exists():
            continue
        documents, records = [], []
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            old = json.loads(line)
            spec = inventory.get((old['apartado'], old['fuente'], old['tipo']))
            if spec is None:
                continue
            doc = dict(old, tipo_dato=spec.get('tipo_dato'), funcion=spec.get('funcion'))
            cached = sonda.corpus / 'cache' / 'sonda' / 'objects' / old['sha256']
            if reextraer_pdf and cached.exists() and cached.read_bytes()[:4] == b'%PDF':
                content = cached.read_bytes()
                if sha256(content).hexdigest() != old['sha256']:
                    raise ValueError(f'Hash del original no coincide: {old["sha256"]}')
                original = Original(content, old['url'], old['retrieved_at'], old['sha256'], True)
                fresh = extract(original, old['fuente'], old['tipo'], max_pages=None)
                # Conserva la evidencia del listado si el PDF no fecha su publicación.
                combined = dict(old)
                combined.update({k: v for k, v in fresh.items()
                                 if k not in ('fecha_publicacion_raw', 'evidencia_publicacion') or v})
                record, doc = sonda._normalize(spec, original, combined, time.monotonic())
            else:
                record = {k: v for k, v in doc.items() if k not in
                          ('texto', 'fragmentos_texto', 'paginas_texto', 'ejemplo_datos')}
                # Los fragmentos antiguos no acreditan páginas que no registraron.
                if not doc.get('fragmentos_texto') and doc.get('texto'):
                    doc['fragmentos_texto'] = chunks(doc['texto'], doc['sha256'])
            documents.append(doc)
            records.append(record)
        frame = pd.DataFrame(records)
        if documents:
            sonda.documents[section] = documents
        metrics_path = sonda.corpus / 'exports' / 'sonda' / f'apartado_{section:02}.csv'
        if metrics_path.exists():
            attempts = pd.read_csv(metrics_path)
            active = {(s['fuente'], s['tipo']) for s in sonda.inventory if s['apartado'] == section}
            failures = attempts.loc[~attempts['estado'].eq('OK')
                                    & attempts.apply(lambda r: (r['fuente'], r['tipo']) in active, axis=1)]
            if not failures.empty:
                frame = pd.concat([frame, failures], ignore_index=True) if not frame.empty else failures.copy()
        if not frame.empty:
            sonda.results[section] = add_metrics(frame)
    return sum(len(group) for group in sonda.documents.values())


@dataclass(frozen=True)
class Exportacion:
    directorio: Path
    bucket: str
    prefijo: str
    catalogo: Path
    manifiesto: Path
    documentos: int
    originales: int
    textos: int
    historicos_acreditados: int

    @property
    def destino_s3(self):
        suffix = f'/{self.prefijo}' if self.prefijo else ''
        return f's3://{self.bucket}{suffix}'


def preparar_corpus(sonda, bucket, prefijo='', destino=None, ejecucion_id=None):
    """Una fila por documento/versión/extractor; snapshots por ejecución.

    El TXT conserva separadores de página y los fragmentos su número de página.
    Un cambio de contenido añade una versión; una reextracción de los mismos
    bytes actualiza su ficha sin rebajar una extracción completa a una parcial.
    """
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket):
        raise ValueError('Indica el nombre del bucket, sin s3:// ni carpetas')
    prefijo = prefijo.strip('/')
    if '\\' in prefijo or any(part in ('.', '..') for part in prefijo.split('/')):
        raise ValueError('Prefijo S3 no válido')
    run = ejecucion_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_') + uuid4().hex[:8]
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run):
        raise ValueError('Identificador de ejecución no válido')
    root = Path(destino) if destino is not None else sonda.corpus / 's3'
    manifest_path = root / 'catalogo' / 'ejecuciones' / run / 'manifiesto.json'
    if manifest_path.exists():
        raise ValueError('La ejecución ya existe: usa un identificador nuevo')
    docs = [d for group in sonda.documents.values() for d in group]
    if not docs:
        raise ValueError('No hay documentos: ejecuta al menos un apartado de la sonda')
    specs = {(s['apartado'], s['fuente'], s['tipo']): s for s in sonda.inventory}
    # Validar la clasificación antes de escribir ningún documento.
    for doc in docs:
        spec = specs.get((doc['apartado'], doc['fuente'], doc['tipo']), {})
        category = doc.get('tipo_dato') or spec.get('tipo_dato')
        if category not in TIPOS_DATO:
            raise ValueError(f'Falta tipo_dato válido para {doc["fuente"]}: {doc["tipo"]}')
        if not re.fullmatch(r'[0-9a-f]{64}', str(doc.get('sha256', ''))):
            raise ValueError('El documento debe identificar el SHA-256 real de su original')
    rows, artifacts, originals, texts = [], {}, set(), set()

    def key(relative):
        return f'{prefijo}/{relative}' if prefijo else relative

    def track(relative):
        path = root / relative
        artifacts[relative] = {'key': key(relative), 'sha256': sha256(path.read_bytes()).hexdigest(),
                               'bytes': path.stat().st_size}

    for doc in docs:
        spec = specs.get((doc['apartado'], doc['fuente'], doc['tipo']), {})
        category = doc.get('tipo_dato') or spec['tipo_dato']
        identity = _identidad(doc)
        digest = doc['sha256']
        cached = sonda.corpus / 'cache' / 'sonda' / 'objects' / digest
        raw_exists = cached.is_file()
        original_key = ''
        extension = str(doc.get('formato') or '')
        if raw_exists:
            content = cached.read_bytes()
            if sha256(content).hexdigest() != digest:
                raise ValueError(f'Hash del original no coincide: {digest}')
            extension = _extension(content, doc.get('formato'))
            original_key = f'{category}/{_slug(doc["fuente"])}/{digest}.{extension}'
            path = root / original_key
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, path)
            track(original_key)
            originals.add(original_key)
        text = doc.get('texto') or ''
        text_hash = sha256(text.encode('utf-8')).hexdigest() if text.strip() else ''
        text_key = f'procesados/txt/{identity}_{text_hash[:20]}.txt' if text_hash else ''
        if text_key:
            path = root / text_key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode('utf-8'))
            track(text_key)
            texts.add(text_key)
        extraction = doc.get('extractor_version') or 'legacy-sin-version'
        row = dict.fromkeys(COLUMNAS, '')
        row.update({k: doc[k] for k in COLUMNAS if doc.get(k) is not None})
        row.update(documento_id=identity, version_id=digest,
                   nombre=doc.get('titulo') or doc['tipo'], entidad=doc['fuente'], familia=doc['tipo'],
                   tipo_dato=category, formato_original=extension, funcion=doc.get('funcion') or spec.get('funcion', ''),
                   region_emisora=REGIONES.get(doc['fuente'], 'Sin_clasificar'),
                   mercados_objetivo='Europa|USA|Asia',
                   idioma=doc.get('idioma') or spec.get('idioma') or 'sin_verificar',
                   licencia=doc.get('licencia') or spec.get('licencia') or 'pendiente_de_verificar',
                   primera_observacion_utc=doc.get('retrieved_at'),
                   paginas_total=doc.get('paginas'), paginas_procesadas=doc.get('paginas_procesadas'),
                   paginas_sin_texto=json.dumps(doc.get('paginas_sin_texto', [])),
                   requiere_revision_ocr=bool(doc.get('requiere_revision_ocr', False)),
                   original_disponible=raw_exists, original_key=key(original_key) if original_key else '',
                   texto_key=key(text_key) if text_key else '',
                   s3_original=f's3://{bucket}/{key(original_key)}' if original_key else '',
                   s3_texto=f's3://{bucket}/{key(text_key)}' if text_key else '',
                   original_sha256=digest, texto_sha256=text_hash, extractor_version=extraction,
                   schema_version=SCHEMA_VERSION, ejecucion_id=run)
        row.update(disponibilidad(doc, raw_exists))
        # No se identifican la fuente emisora y un impacto bursátil demostrado.
        # mercados_objetivo describe el universo de estudio, no una etiqueta causal.
        payload = dict(doc, catalogo=row.copy(), schema_version=SCHEMA_VERSION)
        artifact_id = sha256(json.dumps(payload, sort_keys=True, default=str).encode('utf-8')).hexdigest()
        json_key = f'procesados/json/{artifact_id}.json'
        chunks_key = f'procesados/fragmentos/{artifact_id}.jsonl'
        row.update(documento_key=key(json_key), fragmentos_key=key(chunks_key))
        payload['catalogo'] = row
        _json(root / json_key, payload)
        chunk_path = root / chunks_key
        chunk_path.parent.mkdir(parents=True, exist_ok=True)
        with chunk_path.open('w', encoding='utf-8', newline='\n') as stream:
            for chunk in doc.get('fragmentos_texto', []):
                item = dict(chunk, documento_id=identity, version_id=digest,
                            disponible_desde_utc=row['disponible_desde_utc'],
                            disponible_desde_observacion_utc=row['disponible_desde_observacion_utc'])
                stream.write(json.dumps(item, ensure_ascii=False, default=str) + '\n')
        track(json_key)
        track(chunks_key)
        rows.append(row)
    catalog_path = root / 'catalogo' / 'documentos.csv'
    previous = []
    if catalog_path.exists():
        with catalog_path.open(encoding='utf-8-sig', newline='') as stream:
            previous = list(csv.DictReader(stream))
    merged = {}
    for row in previous + rows:
        identity = tuple(row[k] for k in ('documento_id', 'version_id', 'extractor_version'))
        old = merged.get(identity)
        if old and _verdadero(old.get('texto_completo')) and not _verdadero(row.get('texto_completo')):
            continue
        merged[identity] = row
    _csv(catalog_path, list(merged.values()))
    snapshot_key = f'catalogo/ejecuciones/{run}/documentos.csv'
    _csv(root / snapshot_key, rows)
    track(snapshot_key)
    measured = [frame for frame in sonda.results.values() if not frame.empty]
    if measured:
        attempts = f'catalogo/ejecuciones/{run}/intentos.csv'
        attempt_rows = [row for frame in measured for row in frame.to_dict('records')]
        pd.DataFrame.from_records(attempt_rows).to_csv(root / attempts, index=False, encoding='utf-8-sig')
        track(attempts)
    manifest = {'schema_version': SCHEMA_VERSION, 'ejecucion_id': run,
                'creado_utc': datetime.now(timezone.utc).isoformat(),
                'bucket': bucket, 'prefijo': prefijo,
                'configuracion': {k: getattr(sonda.config, k) for k in
                                  ('max_por_familia', 'max_paginas', 'max_filas', 'usar_cache', 'corte_utc')},
                'inventario_activo': [{k: s[k] for k in ('apartado', 'fuente', 'tipo', 'url', 'tipo_dato') if k in s}
                                      for s in sonda.inventory],
                'documentos_ejecucion': len(rows), 'documentos_catalogo': len(merged),
                'originales_unicos_ejecucion': len(originals), 'textos_ejecucion': len(texts),
                'historicos_acreditados_ejecucion': sum(row['apto_historico_acreditado'] for row in rows),
                'artefactos': list(artifacts.values())}
    _json(manifest_path, manifest)
    return Exportacion(root, bucket, prefijo, catalog_path, manifest_path, len(rows), len(originals), len(texts),
                       manifest['historicos_acreditados_ejecucion'])


def sincronizar_s3(exportacion, simular=True, perfil=None):
    """Subir artefactos primero y publicar el catálogo después; nunca borrar objetos.

    Requiere AWS CLI y una sesión autorizada. La simulación también necesita
    permisos para listar el destino, pero no modifica los objetos del bucket.
    """
    base = ['aws'] + (['--profile', perfil] if perfil else [])
    commands = [base + ['s3', 'sync', str(exportacion.directorio), exportacion.destino_s3,
                        '--exclude', 'catalogo/*'],
                base + ['s3', 'sync', str(exportacion.directorio / 'catalogo'),
                        exportacion.destino_s3 + '/catalogo']]
    results = []
    for command in commands:
        if simular:
            command.append('--dryrun')
        results.append(subprocess.run(command, check=True, text=True, capture_output=True))
    return results
