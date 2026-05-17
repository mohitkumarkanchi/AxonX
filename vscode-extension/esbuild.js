const esbuild = require("esbuild");
const isWatch = process.argv.includes("--watch");

const ctx = esbuild.context({
  entryPoints: ["src/extension.ts"],
  bundle: true,
  outfile: "out/extension.js",
  external: ["vscode"],
  format: "cjs",
  platform: "node",
  target: "node18",
  sourcemap: true,
  minify: !isWatch,
});

ctx.then((c) => {
  if (isWatch) {
    c.watch();
    console.log("Watching...");
  } else {
    c.rebuild().then(() => {
      c.dispose();
      console.log("Build complete.");
    });
  }
});
