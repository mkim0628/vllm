#!/usr/bin/env python3
"""Inspect a PPTX without editing it; JSON output, Python standard library only."""
import argparse
import collections
import json
import posixpath
import xml.etree.ElementTree as ET
import zipfile

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def inspect(filename):
    with zipfile.ZipFile(filename) as z:
        root = ET.fromstring(z.read("ppt/presentation.xml"))
        size = root.find("p:sldSz", NS)
        width, height = int(size.attrib["cx"]), int(size.attrib["cy"])
        rels = {r.attrib["Id"]: r.attrib["Target"] for r in
                ET.fromstring(z.read("ppt/_rels/presentation.xml.rels"))}
        result = {"slide_size_emu": [width, height],
                  "slide_size_inches": [width / 914400, height / 914400],
                  "slides": [], "limits": "Explicit XML styles only. Inherited styles, group transforms, text fit and rendering require visual review."}
        for number, sid in enumerate(root.findall("p:sldIdLst/p:sldId", NS), 1):
            target = rels[sid.attrib["{" + NS["r"] + "}id"]]
            path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("ppt", target))
            slide = ET.fromstring(z.read(path))
            fonts, sizes, colors = collections.Counter(), collections.Counter(), collections.Counter()
            for tag in ("latin", "ea", "cs"):
                fonts.update(x.attrib["typeface"] for x in slide.findall(".//a:" + tag, NS) if "typeface" in x.attrib)
            for tag in ("rPr", "defRPr", "endParaRPr"):
                sizes.update(float(x.attrib["sz"]) / 100 for x in slide.findall(".//a:" + tag, NS) if "sz" in x.attrib)
            colors.update(x.attrib["val"] for x in slide.findall(".//a:srgbClr", NS))
            objects = []
            tree = slide.find("p:cSld/p:spTree", NS)
            for shape in list(tree) if tree is not None else []:
                transform = shape.find("p:spPr/a:xfrm", NS)
                if transform is None:
                    transform = shape.find("p:xfrm", NS)
                text = " ".join(x.text or "" for x in shape.findall(".//a:t", NS))
                entry = {"type": shape.tag.rsplit("}", 1)[-1], "text": text}
                if transform is not None:
                    off, ext = transform.find("a:off", NS), transform.find("a:ext", NS)
                    if off is not None and ext is not None:
                        x, y = int(off.attrib["x"]), int(off.attrib["y"])
                        w, h = int(ext.attrib["cx"]), int(ext.attrib["cy"])
                        entry["box_emu"] = [x, y, w, h]
                        entry["outside_canvas"] = x < 0 or y < 0 or x + w > width or y + h > height
                objects.append(entry)
            notes = ""
            slide_rels = posixpath.join(posixpath.dirname(path), "_rels", posixpath.basename(path) + ".rels")
            if slide_rels in z.namelist():
                for rel in ET.fromstring(z.read(slide_rels)):
                    if rel.attrib.get("Type", "").endswith("/notesSlide"):
                        t = rel.attrib["Target"]
                        npath = t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(path), t))
                        notes = "\n".join(x.text or "" for x in ET.fromstring(z.read(npath)).findall(".//a:t", NS))
            result["slides"].append({"number": number, "part": path,
                                     "text": "\n".join(x.text or "" for x in slide.findall(".//a:t", NS)),
                                     "explicit_fonts": dict(fonts), "explicit_sizes_pt": dict(sizes),
                                     "explicit_rgb": dict(colors), "objects": objects, "notes": notes})
        result["slide_count"] = len(result["slides"])
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pptx")
    args = parser.parse_args()
    print(json.dumps(inspect(args.pptx), ensure_ascii=False, indent=2))
