#!/usr/bin/env python3
import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

FONT = "Times New Roman"
MONO = "Courier New"
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
FOOTER_TYPE = R_NS + "/footer"
FOOTER_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"


def fonts(name=FONT):
    return (f'<w:rFonts w:ascii="{name}" w:hAnsi="{name}" w:cs="{name}" '
            f'w:eastAsia="{name}"/>')


BUILTIN = {"Normal", "BodyText", "Title", "Subtitle", "Caption", "Heading1", "Heading2",
           "Heading3"}


def para(sid, name, ppr, rpr="", based="Normal", nxt="BodyText"):
    custom = "" if sid in BUILTIN else ' w:customStyle="1"'
    default = ' w:default="1"' if sid == "Normal" else ""
    parent = f'<w:basedOn w:val="{based}"/>' if based else ""
    return (f'<w:style w:type="paragraph"{default}{custom} w:styleId="{sid}">'
            f'<w:name w:val="{name}"/>{parent}<w:next w:val="{nxt}"/>'
            f'<w:qFormat/><w:pPr>{ppr}</w:pPr><w:rPr>{rpr}</w:rPr></w:style>')


def body(first=709, jc="both", line=360, before=0, after=0):
    return (f'<w:spacing w:before="{before}" w:after="{after}" w:line="{line}" '
            f'w:lineRule="auto"/><w:ind w:firstLine="{first}"/><w:jc w:val="{jc}"/>')


def heading(level, jc, first, before, after):
    return para(f"Heading{level}", f"heading {level}",
                f'<w:keepNext/><w:keepLines/>{body(first, jc, 360, before, after)}'
                f'<w:outlineLvl w:val="{level - 1}"/>',
                f'{fonts()}<w:b/><w:bCs/><w:sz w:val="28"/><w:szCs w:val="28"/>')


BORDERS = "".join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
                  for side in ("top", "left", "bottom", "right", "insideH", "insideV"))

STYLES = [
    para("Normal", "Normal", body(), f'{fonts()}<w:sz w:val="28"/><w:szCs w:val="28"/>'
         '<w:lang w:val="ru-RU"/>', based="", nxt="Normal"),
    para("BodyText", "Body Text", body()),
    para("FirstParagraph", "First Paragraph", body(), based="BodyText"),
    para("Compact", "Compact", body(0, "left", 360), based="BodyText"),
    para("Cover", "Cover", body(0, "center", 360), nxt="Cover"),
    para("CoverTitle", "CoverTitle", body(0, "center", 360, 3400, 0), "<w:b/>", based="Cover"),
    para("CoverSigned", "CoverSigned", body(0, "right", 360, 2600, 0), based="Cover"),
    para("CoverBottom", "CoverBottom",
         '<w:framePr w:wrap="around" w:vAnchor="margin" w:hAnchor="margin" w:xAlign="center" '
         f'w:yAlign="bottom"/>{body(0, "center", 360)}', based="Cover"),
    para("Title", "Title", body(0, "center", 360, 0, 240), '<w:b/><w:caps/>'),
    para("Subtitle", "Subtitle", body(0, "center", 360, 0, 240)),
    para("Author", "Author", body(0, "right")),
    para("Date", "Date", body(0, "center")),
    heading(1, "center", 0, 240, 240),
    heading(2, "left", 709, 240, 120),
    heading(3, "left", 709, 120, 0),
    para("Caption", "caption", body(0, "center", 360, 120, 240)),
    para("ImageCaption", "Image Caption", body(0, "center", 360, 120, 240), based="Caption"),
    para("TableCaption", "Table Caption", f'<w:keepNext/>{body(0, "left", 360, 240, 0)}',
         based="Caption"),
    para("Figure", "Figure", f'<w:keepNext/>{body(0, "center", 240, 120, 0)}'),
    para("CaptionedFigure", "Captioned Figure", f'<w:keepNext/>{body(0, "center", 240, 120, 0)}',
         based="Figure"),
    para("SourceCode", "Source Code", body(0, "left", 240),
         f'{fonts(MONO)}<w:sz w:val="22"/><w:szCs w:val="22"/>', nxt="BodyText"),
    ('<w:style w:type="character" w:customStyle="1" w:styleId="VerbatimChar">'
     '<w:name w:val="Verbatim Char"/><w:basedOn w:val="DefaultParagraphFont"/>'
     f'<w:rPr>{fonts(MONO)}<w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:style>'),
    ('<w:style w:type="table" w:default="1" w:styleId="Table"><w:name w:val="Table"/>'
     '<w:basedOn w:val="TableNormal"/><w:qFormat/><w:pPr>'
     f'{body(0, "left", 240)}</w:pPr><w:rPr><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr>'
     f'<w:tblPr><w:tblBorders>{BORDERS}</w:tblBorders><w:tblCellMar>'
     '<w:left w:w="108" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr>'
     '<w:tblStylePr w:type="firstRow"><w:rPr><w:b/></w:rPr><w:trPr><w:tblHeader/></w:trPr>'
     '</w:tblStylePr></w:style>'),
]

FOOTER = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {W}><w:p><w:pPr>'
          '<w:jc w:val="center"/><w:ind w:firstLine="0"/></w:pPr>'
          '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
          '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
          '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r>'
          '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>')

SECTION = (f'<w:sectPr><w:footerReference w:type="default" r:id="rIdGostFooter" '
           f'xmlns:r="{R_NS}"/><w:pgSz w:w="11906" w:h="16838"/>'
           '<w:pgMar w:top="1134" w:right="850" w:bottom="1134" w:left="1701" '
           'w:header="709" w:footer="709" w:gutter="0"/><w:titlePg/></w:sectPr>')


def style_id(xml):
    return re.search(r'w:styleId="([^"]+)"', xml).group(1)


def gost_styles(xml):
    for style in STYLES:
        sid = style_id(style)
        xml = re.sub(rf'<w:style [^>]*w:styleId="{sid}"[^>]*>.*?</w:style>\s*', "", xml,
                     flags=re.S)
    xml = re.sub(r"<w:docDefaults>.*?</w:docDefaults>",
                 f'<w:docDefaults><w:rPrDefault><w:rPr>{fonts()}<w:sz w:val="28"/>'
                 '<w:szCs w:val="28"/><w:lang w:val="ru-RU" w:eastAsia="en-US" w:bidi="ar-SA"/>'
                 '</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="0" '
                 'w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>',
                 xml, flags=re.S)
    xml = re.sub(r'<w:rFonts [^>]*w:asciiTheme="[^"]*"[^>]*/>', fonts(), xml)
    xml = re.sub(r"<w:color [^>]*/>", "", xml)
    return xml.replace("</w:styles>", "".join(STYLES) + "</w:styles>")


def gost_document(xml):
    xml = re.sub(r"<w:sectPr\s*/>|<w:sectPr\b.*?</w:sectPr>", "", xml, flags=re.S)
    return xml.replace("</w:body>", SECTION + "</w:body>")


def gost_rels(xml):
    rel = f'<Relationship Id="rIdGostFooter" Type="{FOOTER_TYPE}" Target="footer-gost.xml"/>'
    return xml if "rIdGostFooter" in xml else xml.replace("</Relationships>",
                                                          rel + "</Relationships>")


def gost_types(xml):
    over = f'<Override PartName="/word/footer-gost.xml" ContentType="{FOOTER_CT}"/>'
    return xml if "footer-gost.xml" in xml else xml.replace("</Types>", over + "</Types>")


PATCHES = {"word/styles.xml": gost_styles, "word/document.xml": gost_document,
           "word/_rels/document.xml.rels": gost_rels, "[Content_Types].xml": gost_types}


def reference(source, target):
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename in PATCHES:
                data = PATCHES[item.filename](data.decode("utf-8")).encode("utf-8")
            out.writestr(item, data)
        out.writestr("word/footer-gost.xml", FOOTER)


def default_name(md):
    lab = md.resolve().parent
    if re.fullmatch(r"(lab|hw|idz|kr)\d+", lab.name):
        return lab / f"{lab.parent.name}-{lab.name}-report.docx"
    return md.with_suffix(".docx")


def windows_temp():
    if os.name == "nt":
        return pathlib.Path(tempfile.gettempdir())
    raw = subprocess.run(["cmd.exe", "/c", "echo %TEMP%"], capture_output=True, cwd="/mnt/c",
                         encoding="utf-8", errors="replace", check=True).stdout.strip()
    return pathlib.Path(subprocess.run(["wslpath", "-u", raw], capture_output=True,
                                       encoding="utf-8", check=True).stdout.strip())


def win_path(p):
    if os.name == "nt":
        return str(p)
    return subprocess.run(["wslpath", "-w", str(p)], capture_output=True, encoding="utf-8",
                          check=True).stdout.strip()


def pdf_by_word(docx):
    work = windows_temp() / "study-lab-build"
    work.mkdir(exist_ok=True)
    src, pdf = work / docx.name, work / docx.with_suffix(".pdf").name
    shutil.copy(docx, src)
    script = ("$w=New-Object -ComObject Word.Application; $w.Visible=$false; "
              f"$d=$w.Documents.Open('{win_path(src)}'); $d.Fields.Update() | Out-Null; "
              "foreach($t in $d.TablesOfContents){$t.Update()}; $d.Save(); "
              f"$d.ExportAsFixedFormat('{win_path(pdf)}',17); $d.Close(0); $w.Quit()")
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], check=True,
                   capture_output=True)
    shutil.copy(src, docx)
    shutil.copy(pdf, docx.with_suffix(".pdf"))


def pdf_by_soffice(docx, soffice):
    subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(docx.parent),
                    str(docx)], check=True, capture_output=True)


def to_pdf(docx):
    if shutil.which("powershell.exe"):
        return pdf_by_word(docx)
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        return pdf_by_soffice(docx, soffice)
    raise SystemExit("PDF: нужен Word (Windows или WSL) или LibreOffice (soffice)")


def build(md, out, pdf=False, extra=()):
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise SystemExit("нужен pandoc: https://pandoc.org/installing.html")
    with tempfile.TemporaryDirectory() as tmp:
        base, ref = pathlib.Path(tmp) / "default.docx", pathlib.Path(tmp) / "gost.docx"
        with base.open("wb") as f:
            subprocess.run([pandoc, "--print-default-data-file", "reference.docx"], stdout=f,
                           check=True)
        reference(base, ref)
        subprocess.run([pandoc, md.name, "-o", str(out), "--reference-doc", str(ref),
                        "--resource-path", ".", *extra], cwd=md.parent, check=True)
    if pdf:
        to_pdf(out)
    return out


def main():
    p = argparse.ArgumentParser(description="report.md → .docx по ГОСТ 7.32 (и PDF)")
    p.add_argument("md", type=pathlib.Path)
    p.add_argument("-o", "--out", type=pathlib.Path)
    p.add_argument("--pdf", action="store_true", help="ещё и PDF: Word или LibreOffice")
    args, extra = p.parse_known_args()
    out = (args.out or default_name(args.md)).resolve()
    print(build(args.md.resolve(), out, args.pdf, extra))
    if args.pdf:
        print(out.with_suffix(".pdf"))


if __name__ == "__main__":
    sys.exit(main())
