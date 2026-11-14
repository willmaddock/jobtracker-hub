"""Synthetic DOCX regressions. API imports use conftest's disposable registry."""
import base64
import io
from xml.sax.saxutils import quoteattr
import zipfile

import pytest

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


def make_docx(target="javascript:parent.__docxExecuted=true", *, image=PNG,
              image_type="image/png", external_image=None, style_map=None):
    """Actual OOXML, generated in memory; no Word/python-docx dependency."""
    relationships = [('link', 'hyperlink', target, 'External')]
    relationships.append(('picture', 'image', external_image or 'media/image',
                          'External' if external_image else None))
    rels = ''.join('<Relationship Id={} Type={} Target={} {}/>'.format(
        quoteattr(ident), quoteattr('http://schemas.openxmlformats.org/officeDocument/2006/relationships/' + kind),
        quoteattr(uri), 'TargetMode="External"' if mode else '') for ident, kind, uri, mode in relationships)
    body = '''<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Preview heading</w:t></w:r></w:p>
      <w:p><w:r><w:rPr><w:b/><w:i/></w:rPr><w:t>Résumé &amp; evidence</w:t></w:r></w:p>
      <w:p><w:hyperlink r:id="link"><w:r><w:t>Harmless attack label</w:t></w:r></w:hyperlink></w:p>
      <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>List item</w:t></w:r></w:p>
      <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Table cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
      <w:p><w:r><w:drawing><wp:inline><wp:docPr id="1" name="Embedded image" descr="Test image"/>
      <a:graphic><a:graphicData><pic:pic><pic:blipFill><a:blip r:embed="picture"/></pic:blipFill></pic:pic></a:graphicData></a:graphic>
      </wp:inline></w:drawing></w:r></w:p>'''
    if external_image:
        body = body.replace('r:embed="picture"', 'r:link="picture"')
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        def write(name, data):
            archive.writestr(zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0)), data)
        write('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/media/image" ContentType=' + quoteattr(image_type) + '/></Types>')
        write('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="main" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        write('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body>' + body + '</w:body></w:document>')
        write('word/_rels/document.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + rels + '</Relationships>')
        write('word/styles.xml', '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style></w:styles>')
        write('word/numbering.xml', '<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num></w:numbering>')
        write('word/media/image', image)
        if style_map is not None:
            write('mammoth/style-map', style_map)
    return out.getvalue()


@pytest.fixture
def preview(client, sample_root):
    client.post('/api/workspaces/link', json={'name': 'Preview test', 'path': str(sample_root)})
    def convert(**options):
        original = make_docx(**options)
        path = sample_root / 'synthetic.docx'
        path.write_bytes(original)
        response = client.get('/api/preview-docx', params={'relpath': path.name})
        assert path.read_bytes() == original
        return response
    return convert


@pytest.mark.parametrize('target', ['javascript:parent.__docxExecuted=true', 'JaVaScRiPt:alert(1)',
                                    'https://external.invalid/track', '/api/auth/logout', 'data:text/html,unsafe'])
def test_actual_docx_links_become_inert_text(preview, target):
    response = preview(target=target)
    assert response.status_code == 200
    fragment = response.json()['html']
    assert 'Harmless attack label' in fragment
    assert '<a' not in fragment and 'href=' not in fragment
    assert target not in fragment


def test_formatting_and_embedded_png_survive(preview):
    fragment = preview().json()['html']
    for expected in ['<h1>', '<strong>', '<em>', '<ul>', '<li>', '<table>', '<td>', 'Résumé', 'data:image/png;base64,']:
        assert expected in fragment


def test_embedded_style_maps_are_disabled(preview):
    response = preview(style_map="p => script:fresh")
    assert response.status_code == 200
    assert '<script' not in response.json()['html']
    assert 'Résumé' in response.json()['html']


@pytest.mark.parametrize('image_type,image', [('image/svg+xml', b'<svg onload="alert(1)"/>'),
                                           ('image/png', b'<svg onload="alert(1)"/>')])
def test_active_or_mislabeled_images_are_omitted(preview, image_type, image):
    data = preview(image=image, image_type=image_type).json()
    assert '<img' not in data['html']
    assert data['warnings']


def test_external_images_never_read_files_or_network(preview, tmp_path, monkeypatch):
    import mammoth.docx.files
    sentinel = tmp_path / 'not-a-document-image.txt'
    sentinel.write_text('SYNTHETIC_LOCAL_SENTINEL')
    calls = []
    monkeypatch.setattr(mammoth.docx.files, 'urlopen', lambda uri: calls.append(uri))
    monkeypatch.setattr(mammoth.docx.files, 'open', lambda *args, **kwargs: calls.append(args), raising=False)
    for uri in [sentinel.as_uri(), '../not-a-document-image.txt', 'http://127.0.0.1:1/no-network']:
        response = preview(external_image=uri)
        assert response.status_code in (200, 500)
        assert 'SYNTHETIC_LOCAL_SENTINEL' not in response.text
    assert calls == []


@pytest.mark.parametrize('path,status', [('missing.docx',404), ('../outside.docx',403), ('Applications/Acme Co/Backend Engineer/coverletter.txt',400)])
def test_docx_path_checks_remain_in_force(client, sample_root, preview, path, status):
    # preview fixture links only the disposable sample root.
    response = client.get('/api/preview-docx', params={'relpath':path})
    assert response.status_code == status


def test_broken_docx_has_safe_error_and_original_remains_downloadable(client, sample_root, preview):
    original = b'SYNTHETIC malformed docx, not an archive'
    (sample_root / 'broken.docx').write_bytes(original)
    response = client.get('/api/preview-docx', params={'relpath':'broken.docx'})
    assert response.status_code == 500
    assert str(sample_root) not in response.text
    assert client.get('/api/file', params={'relpath':'broken.docx'}).content == original


def test_converter_passes_security_options_explicitly(preview, monkeypatch):
    import mammoth
    original = mammoth.convert_to_html
    calls = []
    def capture(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(mammoth, 'convert_to_html', capture)
    assert preview().status_code == 200
    assert calls[0]['external_file_access'] is False
    assert calls[0]['include_embedded_style_map'] is False


def test_sanitizer_rejects_active_html_even_from_conversion_changes(monkeypatch):
    import mammoth
    from docx_preview import convert_docx
    from types import SimpleNamespace
    hostile = '<p onclick="alert(1)">Keep</p><script>bad()</script><style>@import "https://external.invalid";</style><iframe src="/api/status"></iframe><meta http-equiv="refresh" content="0;url=https://external.invalid"><form action="/api/auth/logout"><button>Send</button></form><img src="https://external.invalid/beacon"><img src="data:image/svg+xml;base64,PHN2Zz4=">'
    monkeypatch.setattr(mammoth, 'convert_to_html', lambda *a, **k: SimpleNamespace(value=hostile, messages=[]))
    result = convert_docx(io.BytesIO(make_docx()))
    assert result['html'] == '<p>Keep</p><img><img>'  # source-less placeholders have no requests/behavior
