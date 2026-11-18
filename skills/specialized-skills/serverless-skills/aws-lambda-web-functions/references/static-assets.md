# Static Assets

Lambda Web Functions serves static files directly from your framework, with no separate CDN to set
up. That is enough for development and low-traffic internal tools, but the managed domain is
HTTP/1.1 only and returns responses uncompressed regardless of `Accept-Encoding`, and it cannot
carry a custom domain. For a production or performance-sensitive site, put CloudFront in front —
see [domains-and-routing.md](references/domains-and-routing.md).

## Project Structure

```
my-app/
├── index.js
├── package.json
├── public/
│   ├── index.html
│   ├── style.css
│   ├── favicon.ico
│   └── js/app.js
└── node_modules/
```

## Serving (Express)

```javascript
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
const __dirname = dirname(fileURLToPath(import.meta.url));

// Immutable assets (hashed filenames)
app.use('/assets', express.static(join(__dirname, 'public/assets'), {
  maxAge: '365d', immutable: true
}));
// Mutable assets
app.use(express.static(join(__dirname, 'public'), { etag: true }));
```

## SPA Fallback

```javascript
app.use('/api', apiRouter);
app.use(express.static(join(__dirname, 'public')));
// Express 5 (the version this skill installs) uses path-to-regexp v8, which
// rejects a bare '*' route and throws at startup. Use the named wildcard:
app.get('/*splat', (req, res) => res.sendFile(join(__dirname, 'public', 'index.html')));
```

> On Express 4, `app.get('*', ...)` works; on Express 5 it must be `'/*splat'` (or a RegExp like `/.*/`). Following the bare-`'*'` form on Express 5 produces `PathError: Missing parameter name` and the app never starts.

## Packaging

Include public/ in your ZIP:

```bash
zip -r function.zip index.js package.json node_modules/ public/
```

## Size Tips

- Package size is capped — see Service Limits in [SKILL.md](SKILL.md)
- Optimize images (WebP, compressed PNG)
- Minify CSS/JS for production
- For image-heavy sites, host media on S3 separately and reference by URL
- Use a bundler (esbuild, Vite) for larger frontends
