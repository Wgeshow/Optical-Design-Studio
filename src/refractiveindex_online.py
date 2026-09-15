"""Explicit, user-initiated access to the CC0 refractiveindex.info database."""
from __future__ import annotations

import html
import math
import re
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import yaml

CATALOG_URL = "https://raw.githubusercontent.com/polyanskiy/refractiveindex.info-database/main/database/catalog-nk.yml"
DATA_BASE_URL = "https://raw.githubusercontent.com/polyanskiy/refractiveindex.info-database/main/database/data/"
SITE_URL = "https://refractiveindex.info/"
_DATA_PATH = re.compile(r"^[A-Za-z0-9_.+()/\-]+\.ya?ml$")
_TAG = re.compile(r"<[^>]+>")
_RANGE = re.compile(r"([0-9.eE+\-]+)\s*[–—-]\s*([0-9.eE+\-]+)\s*[µμu]m")


def _get(url, limit):
    request = Request(url, headers={"User-Agent": "OpticalDesignStudio/1.0 (+https://refractiveindex.info/)"})
    with urlopen(request, timeout=20) as response:
        if response.geturl().split("/", 3)[:3] != url.split("/", 3)[:3]:
            raise ValueError("The database request was redirected to an unexpected server.")
        length = response.headers.get("Content-Length")
        if length and int(length) > limit:
            raise ValueError("The database response is larger than the safety limit.")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("The database response is larger than the safety limit.")
    return data


def _plain(value):
    return html.unescape(_TAG.sub("", str(value or ""))).strip()


def search_catalog(query, fetch=_get, limit=100):
    """Download only the public catalog and return matching dataset metadata."""
    terms = [term.casefold() for term in re.findall(r"[\w.+-]+", str(query), re.UNICODE) if len(term) > 1]
    if not terms:
        raise ValueError("Enter at least two letters, a chemical formula, or a material name.")
    catalog = yaml.safe_load(fetch(CATALOG_URL, 2_000_000))
    results = []
    for shelf in catalog if isinstance(catalog, list) else []:
        if not isinstance(shelf, dict) or "SHELF" not in shelf:
            continue
        shelf_id, shelf_name = str(shelf["SHELF"]), _plain(shelf.get("name"))
        for book in shelf.get("content", []):
            if not isinstance(book, dict) or "BOOK" not in book:
                continue
            book_id, material = str(book["BOOK"]), _plain(book.get("name"))
            material_text = f"{book_id} {material}".casefold()
            if not all(term in material_text for term in terms):
                continue
            for page in book.get("content", []):
                if not isinstance(page, dict) or "PAGE" not in page or "data" not in page:
                    continue
                path = str(page["data"])
                if not _DATA_PATH.fullmatch(path) or ".." in path.split("/"):
                    continue
                dataset = _plain(page.get("name"))
                match = _RANGE.search(dataset)
                results.append(dict(
                    material=material, material_id=book_id, dataset=dataset,
                    page=str(page["PAGE"]), shelf=shelf_id, shelf_name=shelf_name,
                    data_path=path,
                    wavelength_range=(f"{match.group(1)}–{match.group(2)} µm" if match else "See dataset"),
                    page_url=SITE_URL + "?" + urlencode({"shelf": shelf_id, "book": book_id, "page": page["PAGE"]}),
                ))
    phrase = " ".join(terms)
    def rank(item):
        identifier = item["material_id"].casefold()
        label = item["material"].casefold()
        words = re.findall(r"[\w.+-]+", label, re.UNICODE)
        return (identifier == phrase, label == phrase, phrase in words,
                label.startswith(phrase), -len(label))
    return sorted(results, key=rank, reverse=True)[:limit]


def _numbers(text):
    return [float(value) for value in str(text).split()]


def _formula(kind, coefficients, wavelength):
    c, w = coefficients, wavelength
    if kind == 1:
        value = 1 + c[0] + sum(c[i] * w*w / (w*w - c[i+1]**2) for i in range(1, len(c)-1, 2))
        return math.sqrt(value)
    if kind == 2:
        value = 1 + c[0] + sum(c[i] * w*w / (w*w - c[i+1]) for i in range(1, len(c)-1, 2))
        return math.sqrt(value)
    if kind == 3:
        return math.sqrt(c[0] + sum(c[i] * w**c[i+1] for i in range(1, len(c)-1, 2)))
    if kind == 5:
        return c[0] + sum(c[i] * w**c[i+1] for i in range(1, len(c)-1, 2))
    if kind == 6:
        return 1 + c[0] + sum(c[i] / (c[i+1] - w**-2) for i in range(1, len(c)-1, 2))
    if kind == 7:
        x = w*w - 0.028
        return c[0] + c[1]/x + c[2]/x**2 + c[3]*w*w + c[4]*w**4 + c[5]*w**6
    raise ValueError(f"This dataset uses dispersion formula {kind}, which this release cannot safely convert. Choose a tabulated dataset instead.")


def parse_dataset(raw, result, missing_k=False):
    """Validate one selected YAML file and convert supported data to nm/n/k rows."""
    document = yaml.safe_load(raw)
    if not isinstance(document, dict) or not isinstance(document.get("DATA"), list):
        raise ValueError("The selected file is not a valid refractiveindex.info optical dataset.")
    n_rows, k_rows, nk_rows = [], [], []
    for section in document["DATA"]:
        if not isinstance(section, dict):
            continue
        kind = str(section.get("type", "")).strip().lower()
        if kind in {"tabulated n", "tabulated k", "tabulated nk"}:
            target = {"tabulated n": n_rows, "tabulated k": k_rows, "tabulated nk": nk_rows}[kind]
            width = 3 if kind == "tabulated nk" else 2
            for line in str(section.get("data", "")).splitlines():
                values = _numbers(line)
                if values and len(values) != width:
                    raise ValueError("A tabulated dataset row has the wrong number of columns.")
                if values:
                    target.append([values[0] * 1000, *values[1:]])
        elif kind.startswith("formula "):
            formula_id = int(kind.split()[1])
            low, high = _numbers(section.get("wavelength_range"))
            coefficients = _numbers(section.get("coefficients"))
            count = 401
            n_rows.extend([[1000*w, _formula(formula_id, coefficients, w)]
                           for w in [low + (high-low)*i/(count-1) for i in range(count)]])
    if nk_rows:
        rows = nk_rows
    else:
        if len(n_rows) < 2:
            raise ValueError("The selected dataset has no supported linear refractive-index data.")
        if k_rows:
            from nk_import import parse_nk
            text = "wavelength,n\n" + "\n".join(f"{w} {n}" for w, n in n_rows)
            text += "\nwavelength,k\n" + "\n".join(f"{w} {k}" for w, k in k_rows)
            rows = parse_nk(text, "nm")
        elif missing_k:
            rows = [[w, n, 0.] for w, n in n_rows]
        else:
            raise ValueError("This dataset contains n but no k. Explicitly allow the lossless k = 0 assumption to import it.")
    if len(rows) < 2 or any(not all(math.isfinite(float(v)) for v in row) for row in rows):
        raise ValueError("The selected dataset did not produce valid finite n,k samples.")
    reference = _plain(document.get("REFERENCES"))
    comments = _plain(document.get("COMMENTS"))
    conditions = document.get("CONDITIONS") if isinstance(document.get("CONDITIONS"), dict) else {}
    return rows, reference, comments, conditions


def download_dataset(result, missing_k=False, fetch=_get):
    """Fetch exactly one previously selected catalog entry; never called by search."""
    if not isinstance(result, dict) or not _DATA_PATH.fullmatch(str(result.get("data_path", ""))):
        raise ValueError("Select a valid catalog result before downloading.")
    path = str(result["data_path"])
    if ".." in path.split("/"):
        raise ValueError("Invalid dataset path.")
    raw = fetch(DATA_BASE_URL + quote(path, safe="/+-.()_"), 5_000_000)
    rows, reference, comments, conditions = parse_dataset(raw, result, missing_k)
    return dict(result=result, rows=rows, reference=reference, comments=comments,
                conditions=conditions, original=raw)
