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

    // Forward messages from the webview to the agent server
    webviewView.webview.onDidReceiveMessage(async (msg) => {
      switch (msg.command) {
        case "sendMessage":
          await this._postChat(msg.text);
          break;
        case "approve":
          await this._postAction("/api/operations/approve");
          break;
        case "cancel":
          await this._postAction("/api/operations/cancel");
          break;
        case "getStatus":
          await this._fetchStatus();
          break;
      }
    });
  }

  notifyServerStatus(status: "connected" | "connecting" | "disconnected"): void {
    this._view?.webview.postMessage({ type: "serverStatus", status });
  }

  // -------------------------------------------------------------------------

  private async _postChat(message: string): Promise<void> {
    try {
      const res = await fetch(`http://127.0.0.1:${this._port}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      if (!res.ok) {
        this._view?.webview.postMessage({
          type: "error",
          message: `Server returned ${res.status}`,
        });
      }
    } catch (err) {
      this._view?.webview.postMessage({
        type: "error",
        message: `Could not reach agent server: ${err}`,
      });
    }
  }

  private async _postAction(endpoint: string): Promise<void> {
    try {
      await fetch(`http://127.0.0.1:${this._port}${endpoint}`, { method: "POST" });
    } catch (err) {
      this._view?.webview.postMessage({
        type: "error",
        message: `Action failed: ${err}`,
      });
    }
  }

  private async _fetchStatus(): Promise<void> {
    try {
      const res = await fetch(`http://127.0.0.1:${this._port}/api/status`);
      if (res.ok) {
        const data = await res.json() as Record<string, unknown>;
        this._view?.webview.postMessage({ type: "status", data });
      }
    } catch {
      // Server not ready yet — ignore
    }
  }

  // -------------------------------------------------------------------------

  private _getHtml(webview: vscode.Webview): string {
    const mediaDir = path.join(this._context.extensionPath, "media");

    const cssUri = webview.asWebviewUri(
      vscode.Uri.file(path.join(mediaDir, "sidebar.css"))
    );
    const jsUri = webview.asWebviewUri(
      vscode.Uri.file(path.join(mediaDir, "sidebar.js"))
    );

    // Inline HTML template with URIs injected
    const htmlPath = path.join(mediaDir, "sidebar.html");
    let html = fs.readFileSync(htmlPath, "utf-8");
    html = html
      .replace("{{CSS_URI}}", cssUri.toString())
      .replace("{{JS_URI}}", jsUri.toString())
      .replace("{{PORT}}", String(this._port));

    return html;
  }
}
