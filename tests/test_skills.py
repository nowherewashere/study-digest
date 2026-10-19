import importlib.util
import re
import unittest
import zipfile

from study import agent
from study.config import SKILLS as PROFILE_SKILLS
from tests.fakes import tmpdir

HERE = agent.HERE
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    head = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return dict(re.findall(r"^(\w+): (.+)$", head.group(1), re.M)), head.group(1), text


def load_build():
    spec = importlib.util.spec_from_file_location(
        "build", HERE / "skills" / "study-lab" / "scripts" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SkillFormatTest(unittest.TestCase):
    def test_every_skill_is_valid_and_owned(self):
        names = sorted(agent.wanted())
        self.assertEqual(names, ["lab-release-with-screencasts", "study-course", "study-digest",
                                 "study-lab", "study-task", "study-update"])
        for name in names:
            fields, head, text = frontmatter(HERE / "skills" / name / "SKILL.md")
            self.assertEqual(fields["name"], name)
            self.assertTrue(NAME.match(name) and len(name) <= 64)
            self.assertTrue(20 < len(fields["description"]) <= 1024, name)
            self.assertIn(agent.OWNER, head)
            self.assertTrue(agent.ours(HERE / "skills" / name))
            self.assertNotIn("study answer", text)

    def test_profiles_and_core_name_existing_skills(self):
        names = set(agent.wanted())
        self.assertLessEqual(set(PROFILE_SKILLS.values()), names)
        core = agent.SOURCE.read_text(encoding="utf-8")
        for name in names:
            self.assertIn(f"`{name}`", core)


class GostReferenceTest(unittest.TestCase):
    def test_reference_patch(self):
        build = load_build()
        tmp = tmpdir(self)
        src, out = tmp / "default.docx", tmp / "gost.docx"
        styles = ('<w:styles><w:docDefaults><w:rPrDefault/></w:docDefaults>'
                  '<w:style w:type="paragraph" w:styleId="Heading1"><w:rPr>'
                  '<w:rFonts w:asciiTheme="majorHAnsi"/><w:color w:val="4F81BD"/></w:rPr>'
                  '</w:style><w:style w:type="paragraph" w:styleId="Other"><w:rPr>'
                  '<w:rFonts w:asciiTheme="minorHAnsi"/></w:rPr></w:style></w:styles>')
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("word/styles.xml", styles)
            z.writestr("word/document.xml", "<w:document><w:body><w:p/><w:sectPr />"
                                            "</w:body></w:document>")
            z.writestr("word/_rels/document.xml.rels", "<Relationships></Relationships>")
            z.writestr("[Content_Types].xml", "<Types></Types>")
        build.reference(src, out)
        with zipfile.ZipFile(out) as z:
            st = z.read("word/styles.xml").decode()
            doc = z.read("word/document.xml").decode()
            rels = z.read("word/_rels/document.xml.rels").decode()
            types = z.read("[Content_Types].xml").decode()
            footer = z.read("word/footer-gost.xml").decode()
        self.assertNotIn("Theme", st)
        self.assertNotIn("4F81BD", st)
        self.assertEqual(st.count('w:styleId="Heading1"'), 1)
        for sid in ("Normal", "Cover", "CoverTitle", "CoverSigned", "CoverBottom", "Table",
                    "SourceCode", "ImageCaption"):
            self.assertIn(f'w:styleId="{sid}"', st)
        self.assertIn('w:ascii="Times New Roman"', st)
        self.assertIn('<w:sz w:val="28"/>', st)
        self.assertIn('w:line="360"', st)
        self.assertIn('<w:pgMar w:top="1134" w:right="850" w:bottom="1134" w:left="1701"', doc)
        self.assertIn("<w:titlePg/>", doc)
        self.assertEqual(doc.count("<w:sectPr"), 1)
        self.assertIn('Target="footer-gost.xml"', rels)
        self.assertIn('PartName="/word/footer-gost.xml"', types)
        self.assertIn(" PAGE ", footer)

    def test_default_name(self):
        build = load_build()
        tmp = tmpdir(self)
        md = tmp / "num-methods" / "lab03" / "report.md"
        self.assertEqual(build.default_name(md),
                         tmp / "num-methods" / "lab03" / "num-methods-lab03-report.docx")
        self.assertEqual(build.default_name(tmp / "notes" / "x.md"), tmp / "notes" / "x.docx")


if __name__ == "__main__":
    unittest.main()
