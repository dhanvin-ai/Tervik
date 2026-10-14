"""Build Tervik's LinkedIn banner from the site's own logo, fonts, and symbol field.

Writes banner.html (self-contained) and renders linkedin-banner.png (1584x396, LinkedIn's
profile size) and linkedin-banner@2x.png with headless Chrome:

    python3 brand/linkedin-banner/build.py
"""
import base64
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WIDTH, HEIGHT = 1584, 396


def font(package, weight):
    path = ROOT / "node_modules" / "@fontsource" / package / "files" / f"{package}-latin-{weight}-normal.woff2"
    return base64.b64encode(path.read_bytes()).decode()


def logo_paths():
    """The mark's three panels and the wordmark, straight from the site's logo component."""
    source = (ROOT / "apps" / "web" / "src" / "components" / "TervikLogo.tsx").read_text()
    panels = re.findall(r"'(M[^']+)'", source.split("export const TERVIK_PANELS", 1)[1].split("];", 1)[0])
    wordmark = re.search(r"const WORDMARK = '([^']+)'", source).group(1)
    return panels, wordmark


def html():
    panels, wordmark = logo_paths()
    logo = ("<svg class='logo' viewBox='0 0 1173 323' role='img' aria-label='Tervik'>"
            + "".join(f"<path d='{d}'/>" for d in panels)
            + f"<path d='{wordmark}' fill-rule='evenodd'/></svg>")
    return (HERE / "template.html").read_text().replace("__LOGO__", logo) \
        .replace("__SANS_400__", font("geist-sans", 400)).replace("__SANS_500__", font("geist-sans", 500)) \
        .replace("__MONO_400__", font("geist-mono", 400)).replace("__MONO_500__", font("geist-mono", 500))


def render(page, out, scale):
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--mute-audio",
                    f"--window-size={WIDTH},{HEIGHT}", f"--force-device-scale-factor={scale}",
                    "--default-background-color=000000ff", "--virtual-time-budget=4000",
                    f"--screenshot={out}", page.as_uri()], check=True, capture_output=True)


if __name__ == "__main__":
    page = HERE / "banner.html"
    page.write_text(html())
    render(page, HERE / "linkedin-banner.png", 1)
    render(page, HERE / "linkedin-banner@2x.png", 2)
    print("Wrote banner.html, linkedin-banner.png, linkedin-banner@2x.png")
