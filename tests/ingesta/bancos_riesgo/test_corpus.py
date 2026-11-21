"""Contrato del catálogo, conservación del original y límites de información."""

import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest

from ingesta.bancos_riesgo.sonda import ConfigSonda, Sonda
from ingesta.bancos_riesgo.sonda.corpus import (
    Exportacion, cargar_muestras_guardadas, disponibilidad, filtrar_catalogo, preparar_corpus, sincronizar_s3,
)
from ingesta.bancos_riesgo.sonda.http import Original
from ingesta.bancos_riesgo.sonda.parsing import chunks, extract


def pdf_bytes(texts):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        if text:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                     NameObject('/Subtype'): NameObject('/Type1'),
                                     NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
                NameObject('/F1'): writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(f'BT /F1 12 Tf 30 700 Td ({text}) Tj ET'.encode('ascii'))
            page[NameObject('/Contents')] = writer._add_object(stream)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def make_probe(tmp_path, content=b'<html>original bytes</html>'):
    digest = sha256(content).hexdigest()
    corpus = tmp_path / 'corpus'
    objects = corpus / 'cache' / 'sonda' / 'objects'
    objects.mkdir(parents=True)
    (objects / digest).write_bytes(content)
    text = 'A full policy communication. ' * 20
    doc = dict(apartado=1, fuente='Fed', tipo='Comunicado', titulo='Policy decision',
               url='https://example.test/statement', texto=text, formato='HTML', sha256=digest,
               version_id=digest, tipo_dato='politica_monetaria', texto_completo=True,
               fecha_publicacion='2020-01-01', precision_publicacion='día', zona_fuente='America/New_York',
               version_acreditada=False, evidencia_version='',
               retrieved_at='2026-11-18T12:00:00+00:00',
               fragmentos_texto=chunks(text, digest), extractor_version='test-v1')
    spec = dict(apartado=1, fuente='Fed', tipo='Comunicado', tipo_dato='politica_monetaria')
    probe = SimpleNamespace(corpus=corpus, documents={1: [doc]}, inventory=[spec], results={},
                            config=ConfigSonda(raiz=tmp_path))
    return probe, doc


def read_catalog(export):
    return pd.read_csv(export.catalogo, keep_default_na=False)


def test_pdf_full_text_keeps_page_references_and_flags_truncation():
    content = pdf_bytes(['First page policy and inflation. ' * 8, 'Second page growth and risk. ' * 8])
    original = Original(content, 'https://x.test/doc.pdf', '2026-11-18T12:00:00Z', sha256(content).hexdigest())
    full = extract(original, 'Fed', 'Report', max_pages=None)
    assert full['texto_completo']
    assert full['paginas_procesadas'] == 2
    assert '\f' in full['texto']
    segments = chunks(full['texto'], original.sha256, pages=full['paginas_texto'])
    assert {c['pagina'] for c in segments} == {1, 2}
    assert len({c['chunk_id'] for c in segments}) == len(segments)
    partial = extract(original, 'Fed', 'Report', max_pages=1)
    assert not partial['texto_completo']
    assert partial['estado_extraccion'] == 'parcial_limite_paginas'


def test_pdf_without_text_is_preserved_but_not_historical():
    content = pdf_bytes([''])
    original = Original(content, 'https://x.test/scan.pdf', '2026-11-18T12:00:00Z', sha256(content).hexdigest())
    result = extract(original, 'Fed', 'Scanned report', max_pages=None)
    assert result['requiere_revision_ocr']
    assert result['paginas_sin_texto'] == [1]
    assert not result['texto_completo']
    assert not disponibilidad(dict(result, version_acreditada=True))['apto_historico_acreditado']


def test_catalog_stores_original_txt_metadata_and_real_s3_keys(tmp_path):
    probe, doc = make_probe(tmp_path)
    result = preparar_corpus(probe, 'tfm-rag-multiagent', prefijo='bancos', ejecucion_id='run_1')
    row = read_catalog(result).iloc[0]
    relative = row['original_key'].removeprefix('bancos/')
    assert (result.directorio / relative).read_bytes() == b'<html>original bytes</html>'
    txt = result.directorio / row['texto_key'].removeprefix('bancos/')
    assert txt.read_text(encoding='utf-8') == doc['texto']
    assert row['nombre'] == 'Policy decision'
    assert row['tipo_dato'] == 'politica_monetaria'
    assert row['s3_original'].startswith('s3://tfm-rag-multiagent/bancos/politica_monetaria/fed/')
    assert row['s3_texto'].startswith('s3://tfm-rag-multiagent/bancos/procesados/txt/')
    assert probe.corpus.joinpath('cache/sonda/objects', doc['sha256']).exists()
    manifest = json.loads(result.manifiesto.read_text(encoding='utf-8'))
    assert 'hf_token' not in json.dumps(manifest)
    for item in manifest['artefactos']:
        artifact = result.directorio / item['key'].removeprefix('bancos/')
        assert sha256(artifact.read_bytes()).hexdigest() == item['sha256']


def test_old_publication_does_not_backdate_current_download(tmp_path):
    probe, doc = make_probe(tmp_path)
    result = preparar_corpus(probe, 'tfm-rag-multiagent')
    catalog = read_catalog(result)
    assert filtrar_catalogo(catalog, '2020-01-02T23:00:00Z').empty
    assert filtrar_catalogo(catalog, '2026-11-18T11:59:59Z', modo='observado').empty
    assert len(filtrar_catalogo(catalog, doc['retrieved_at'], modo='observado')) == 1
    assert filtrar_catalogo(catalog, '2030-01-01T00:00:00Z').empty


def test_boolean_certificate_alone_is_not_evidence(tmp_path):
    _, doc = make_probe(tmp_path)
    doc['version_acreditada'] = True
    assert not disponibilidad(doc)['apto_historico_acreditado']
    doc['evidencia_version'] = 'Archived copy and release evidence verified for this content hash'
    result = disponibilidad(doc)
    assert result['apto_historico_acreditado']
    assert result['disponible_desde_utc'] == '2020-01-02T05:00:00+00:00'


def test_future_release_and_timezone_cutoff(tmp_path):
    probe, doc = make_probe(tmp_path)
    doc.update(fecha_publicacion='2026-11-19T15:00:00-05:00', precision_publicacion='hora',
               publicacion_utc='2026-11-19T20:00:00+00:00')
    result = preparar_corpus(probe, 'tfm-rag-multiagent')
    catalog = read_catalog(result)
    assert filtrar_catalogo(catalog, '2026-11-19T19:59:59Z', modo='observado').empty
    assert len(filtrar_catalogo(catalog, '2026-11-19T20:00:00Z', modo='observado')) == 1
    with pytest.raises(ValueError, match='zona'):
        filtrar_catalogo(catalog, '2026-11-20')


def test_missing_original_and_partial_text_cannot_enter_backtest(tmp_path):
    probe, doc = make_probe(tmp_path)
    doc.update(version_acreditada=True, evidencia_version='Verified edition')
    assert not disponibilidad(dict(doc, texto_completo=False))['apto_historico_acreditado']
    assert not disponibilidad(doc, original_disponible=False)['apto_desde_observacion']
    (probe.corpus / 'cache/sonda/objects' / doc['sha256']).unlink()
    result = preparar_corpus(probe, 'tfm-rag-multiagent')
    assert not read_catalog(result).iloc[0]['original_disponible']


def test_catalog_preserves_versions_without_duplicating_reruns(tmp_path):
    probe, doc = make_probe(tmp_path)
    first = preparar_corpus(probe, 'tfm-rag-multiagent', ejecucion_id='first')
    second = preparar_corpus(probe, 'tfm-rag-multiagent', ejecucion_id='second')
    assert len(read_catalog(second)) == 1
    assert first.manifiesto.exists()
    new_content = b'<html>revised content</html>'
    digest = sha256(new_content).hexdigest()
    (probe.corpus / 'cache/sonda/objects' / digest).write_bytes(new_content)
    doc.update(sha256=digest, version_id=digest, texto='Revised document. ' * 20)
    third = preparar_corpus(probe, 'tfm-rag-multiagent', ejecucion_id='third')
    assert len(read_catalog(third)) == 2
    assert len(list((third.directorio / 'politica_monetaria/fed').glob('*.html'))) == 2
    with pytest.raises(ValueError, match='ya existe'):
        preparar_corpus(probe, 'tfm-rag-multiagent', ejecucion_id='third')


def test_partial_rerun_does_not_replace_complete_extraction(tmp_path):
    probe, doc = make_probe(tmp_path)
    first = preparar_corpus(probe, 'tfm-rag-multiagent')
    doc.update(texto_completo=False, texto='First paragraphs only.')
    second = preparar_corpus(probe, 'tfm-rag-multiagent')
    catalog = read_catalog(second)
    assert len(catalog) == 1
    assert catalog.iloc[0]['texto_completo']
    assert first.manifiesto.exists()


def test_qa_and_full_document_have_separate_texts_and_one_original(tmp_path):
    probe, doc = make_probe(tmp_path)
    qa = dict(doc, tipo='Preguntas y respuestas', texto='Questions? Answers. ' * 10, texto_completo=False)
    probe.documents[1].append(qa)
    result = preparar_corpus(probe, 'tfm-rag-multiagent')
    catalog = read_catalog(result)
    assert len(catalog) == 2
    assert catalog['documento_id'].nunique() == 2
    assert catalog['original_key'].nunique() == 1
    assert catalog['texto_key'].nunique() == 2
    assert result.originales == 1


@pytest.mark.parametrize('change', ['wrong_hash', 'unclassified'])
def test_corrupt_or_unclassified_input_is_rejected(tmp_path, change):
    probe, doc = make_probe(tmp_path)
    if change == 'wrong_hash':
        (probe.corpus / 'cache/sonda/objects' / doc['sha256']).write_bytes(b'corrupt')
    else:
        doc['tipo_dato'] = '../other'
    with pytest.raises(ValueError):
        preparar_corpus(probe, 'tfm-rag-multiagent')


def test_s3_simulates_by_default_and_uploads_catalog_last(tmp_path):
    export = Exportacion(tmp_path, 'tfm-rag-multiagent', '', tmp_path / 'catalogo/documentos.csv',
                         tmp_path / 'catalogo/run.json', 1, 1, 1, 0)
    with patch('ingesta.bancos_riesgo.sonda.corpus.subprocess.run') as run:
        sincronizar_s3(export)
    commands = [c.args[0] for c in run.call_args_list]
    assert len(commands) == 2
    assert all('--dryrun' in c and '--delete' not in c for c in commands)
    assert 'catalogo/*' in commands[0]
    assert commands[1][-2] == 's3://tfm-rag-multiagent/catalogo'
    with patch('ingesta.bancos_riesgo.sonda.corpus.subprocess.run',
               side_effect=subprocess.CalledProcessError(1, 'aws')) as run:
        with pytest.raises(subprocess.CalledProcessError):
            sincronizar_s3(export, simular=False)
        assert run.call_count == 1


def test_real_upload_requires_explicit_choice_and_supports_profile(tmp_path):
    probe, _ = make_probe(tmp_path)
    export = preparar_corpus(probe, 'tfm-rag-multiagent')
    with patch('ingesta.bancos_riesgo.sonda.corpus.subprocess.run') as run:
        sincronizar_s3(export, simular=False, perfil='tfm')
    commands = [c.args[0] for c in run.call_args_list]
    assert all('--dryrun' not in c and '--delete' not in c for c in commands)
    assert commands[0][:3] == ['aws', '--profile', 'tfm']


def test_csv_has_headers_when_missing_fields_are_unknown(tmp_path):
    probe, doc = make_probe(tmp_path)
    doc.update(fecha_publicacion=None, precision_publicacion='desconocida')
    export = preparar_corpus(probe, 'tfm-rag-multiagent')
    with export.catalogo.open(encoding='utf-8-sig', newline='') as stream:
        row = next(csv.DictReader(stream))
    assert row['fecha_publicacion'] == ''
    assert row['licencia'] == 'pendiente_de_verificar'
    assert row['idioma'] == 'sin_verificar'
    assert not row['disponible_desde_utc']


def test_saved_pdf_is_reextracted_offline_and_inactive_families_are_omitted(tmp_path):
    content = pdf_bytes(['First page with a policy decision. ' * 8, 'Second page with more context. ' * 8])
    fixture, doc = make_probe(tmp_path, content)
    doc.update(formato='PDF', texto_completo=False, fecha_publicacion_raw='January 1, 2020',
               evidencia_publicacion='Publication label observed in listing')
    spec = dict(fixture.inventory[0], adaptador='documento', url=doc['url'])
    inventory = tmp_path / 'inventory.json'
    inventory.write_text(json.dumps([spec]), encoding='utf-8')
    folder = fixture.corpus / 'local/sonda'
    folder.mkdir(parents=True)
    folder.joinpath('apartado_01.jsonl').write_text(
        json.dumps(doc) + '\n' + json.dumps(dict(doc, tipo='Inactive old family')) + '\n', encoding='utf-8')
    probe = Sonda(ConfigSonda(raiz=tmp_path, inventario=inventory, directorio_corpus=fixture.corpus))
    with patch('ingesta.comun.http.get', side_effect=AssertionError('Must remain offline')):
        assert cargar_muestras_guardadas(probe) == 1
    loaded = probe.documents[1][0]
    assert loaded['texto_completo']
    assert loaded['paginas_procesadas'] == 2
    assert loaded['fecha_publicacion'] == '2020-01-01'
    assert not loaded['version_acreditada']
    assert {c['pagina'] for c in loaded['fragmentos_texto']} == {1, 2}
    assert len(folder.joinpath('apartado_01.jsonl').read_text(encoding='utf-8').splitlines()) == 2


def test_saved_failures_are_preserved_even_for_a_section_with_no_documents(tmp_path):
    spec = dict(apartado=6, fuente='FMI', tipo='WEO', adaptador='documento',
                tipo_dato='informes_macro', url='https://example.test/weo')
    inventory = tmp_path / 'inventory.json'
    inventory.write_text(json.dumps([spec]), encoding='utf-8')
    corpus = tmp_path / 'corpus'
    folder = corpus / 'local/sonda'
    folder.mkdir(parents=True)
    folder.joinpath('apartado_06.jsonl').write_text('', encoding='utf-8')
    metrics = corpus / 'exports/sonda'
    metrics.mkdir(parents=True)
    record = Sonda._base(spec, spec['url'])
    record.update(estado='EXCLUIDA', error='Known access restriction')
    pd.DataFrame([record]).to_csv(metrics / 'apartado_06.csv', index=False)
    probe = Sonda(ConfigSonda(raiz=tmp_path, inventario=inventory, directorio_corpus=corpus))
    assert cargar_muestras_guardadas(probe) == 0
    assert probe.results[6].iloc[0]['estado'] == 'EXCLUIDA'
