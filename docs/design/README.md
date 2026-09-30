# Broadsheet design mockups

`web.html` and `device.html` are the mockups that set block 3's starting direction in September 2026,
before the publisher was built. `device.html` draws three 1872 by 1404 compositions (`?v=A`, `?v=B`,
`?v=C`); `web.html` is the web edition of the same day. `preview/` holds renderings of them. They are
historical: the publisher builds one device composition, lead-wide, and its web grid and sheet
compositions from its own templates, and the mockups were not updated to follow.

They are not the token source. They load Playfair Display and Source Serif 4 from Google Fonts;
production uses Newsreader and Libre Franklin from vendored files, at different sizes. The production
stylesheets in `publisher/assets/css/` (`tokens.css`, `web.css`, `device.css`) are authoritative on
type, colour, geometry, and composition; see [publisher-architecture.md](../publisher-architecture.md).

Open a mockup in a browser with an internet connection for the fonts, or render a device composition
with headless Chrome:

```
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu \
  --hide-scrollbars --force-device-scale-factor=1 --window-size=1920,1500 \
  --screenshot=/tmp/A.png "file://$PWD/docs/design/device.html?v=A"
```
