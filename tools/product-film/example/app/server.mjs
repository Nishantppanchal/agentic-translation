// Serves the example app, so the toolkit can be tried without any backend.
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
http
  .createServer((req, res) => {
    res.setHeader("content-type", "text/html; charset=utf-8");
    res.end(fs.readFileSync(path.join(here, "index.html")));
  })
  .listen(4173, "127.0.0.1");
