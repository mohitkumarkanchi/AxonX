import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";

export class SidebarProvider implements vscode.WebviewViewProvider {
  private _view?: vscode.WebviewView;
  private _port: number;
  private _context: vscode.ExtensionContext;

  constructor(context: vscode.ExtensionContext, port: number) {
    this._context = context;
    this._port = port;
  }

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _resolverContext: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [
        vscode.Uri.file(path.join(this._context.extensionPath, "media")),
      ],
    };

    webviewView.webview.html = this._getHtml(webviewView.webview);

    // Forward messages from the webview to the extension host
    webviewView.webview.onDidReceiveMessage(async (msg) => {
      switch (msg.command) {
        case "openFile":
          if (msg.filePath) {
            try {
              const rootPath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || "";
              const fullPath = path.isAbsolute(msg.filePath) ? msg.filePath : path.join(rootPath, msg.filePath);
              if (fs.existsSync(fullPath)) {
                const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(fullPath));
                await vscode.window.showTextDocument(doc);
              }
            } catch (err) {
              vscode.window.showErrorMessage(`Failed to open file: ${err}`);
            }
          }
          break;
      }
    });
  }

  notifyServerStatus(status: "connected" | "connecting" | "disconnected"): void {
    this._view?.webview.postMessage({ type: "serverStatus", status });
  }

  private _getHtml(webview: vscode.Webview): string {
    const mediaDir = path.join(this._context.extensionPath, "media");

    const cssUri = webview.asWebviewUri(
      vscode.Uri.file(path.join(mediaDir, "sidebar.css"))
    );
    const jsUri = webview.asWebviewUri(
      vscode.Uri.file(path.join(mediaDir, "sidebar.js"))
    );

    // Inline HTML template with URIs injected (equipped with version cache-buster)
    const htmlPath = path.join(mediaDir, "sidebar.html");
    let html = fs.readFileSync(htmlPath, "utf-8");
    html = html
      .replace("{{CSS_URI}}", `${cssUri.toString()}?v=${Date.now()}`)
      .replace("{{JS_URI}}", `${jsUri.toString()}?v=${Date.now()}`)
      .replace(/{{PORT}}/g, String(this._port));

    return html;
  }
}
