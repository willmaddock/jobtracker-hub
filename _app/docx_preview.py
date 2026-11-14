"""Read-only conversion of untrusted DOCX into an inert formatting fragment.

This is a legacy preview adapter, not a shared Django/filesystem abstraction.
The caller retains path/ownership checks. The renderer must still sandbox it.
"""
import base64

import mammoth
import nh3


_TAGS = {
    'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'em', 'b', 'i',
    'u', 's', 'strike', 'sup', 'sub', 'ul', 'ol', 'li', 'blockquote', 'pre',
    'code', 'hr', 'table', 'caption', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
    'img', 'dl', 'dt', 'dd',
}
_CONTENT_REMOVED = {'script', 'style', 'iframe', 'object', 'embed', 'form',
                    'svg', 'math', 'template', 'textarea', 'button', 'select'}


def _raster_matches(content_type, data):
    # Do not trust a document's claimed MIME type, or admit SVG/data HTML.
    # The browser still decodes these images inside a scriptless opaque frame.
    return (
        content_type == 'image/png' and data.startswith(b'\x89PNG\r\n\x1a\n')
        or content_type == 'image/jpeg' and data.startswith(b'\xff\xd8\xff')
        or content_type == 'image/gif' and data[:6] in (b'GIF87a', b'GIF89a')
        or content_type == 'image/webp' and data[:4] == b'RIFF' and data[8:12] == b'WEBP'
    )


def convert_docx(fileobj):
    """Return the existing {html, warnings} API shape; never write source files."""
    approved_images = set()
    warnings = []

    def image_converter(image):
        with image.open() as stream:
            data = stream.read()
        content_type = image.content_type.lower()
        if not _raster_matches(content_type, data):
            warnings.append('An unsupported or invalid embedded image was omitted from the preview.')
            return []
        src = 'data:' + content_type + ';base64,' + base64.b64encode(data).decode('ascii')
        approved_images.add(src)
        return mammoth.images.img_element(lambda _: {'src': src})(image)

    result = mammoth.convert_to_html(
        fileobj, external_file_access=False, include_embedded_style_map=False,
        convert_image=image_converter,
    )

    def attribute(tag, name, value):
        if name == 'src':
            return value if tag == 'img' and value in approved_images else None
        if name in {'colspan', 'rowspan', 'start', 'value'}:
            return value if len(value) <= 5 and value.isascii() and value.isdecimal() and 0 < int(value) <= 10000 else None
        return value if tag == 'img' and name == 'alt' else None

    cleaner = nh3.Cleaner(
        tags=_TAGS, clean_content_tags=_CONTENT_REMOVED,
        attributes={'img': {'src', 'alt'}, 'td': {'colspan', 'rowspan'},
                    'th': {'colspan', 'rowspan'}, 'ol': {'start'}, 'li': {'value'}},
        attribute_filter=attribute, url_schemes={'data'}, url_relative='deny',
        strip_comments=True, link_rel=None,
    )
    return {'html': cleaner.clean(result.value),
            'warnings': [str(message) for message in result.messages] + warnings}
