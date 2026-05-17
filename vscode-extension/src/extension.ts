import * as vscode from "vscode";
import * as path from "path";
import * as http from "http";
import * as cp from "child_process";
import * as fs from "fs";
import { SidebarProvider } from "./sidebarProvider";

let serverProcess: cp.ChildProcess | undefined;
let sidebarProvider: SidebarProvider | undefined;

export function activate(context: vscode.ExtensionContext) {
  const config = vscode.workspace.getConfiguration("localAgent");
  const port: number = config.get("port", 7070);
  const autoStart: boolean = config.get("autoStart", true);

  sidebarProvider = new SidebarProvider(context, port);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      "local-agent.sidebar",
      sidebarProvider,
      { webviewOptions: { retainContextWhenHidden: true } }
    )
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("local-agent.openSidebar", () => {
      vscode.commands.executeCommand("local-agent.sidebar.focus");
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("local-agent.restartServer", async () => {
      await stopServer();
      await startServer(context, port);
      sidebarProvider?.notifyServerStatus("connecting");
    })
  );

  if (autoStart) {
    isServerRunning(port).then((running) => {
      if (running) {
        // Existing server — connect directly
        sidebarProvider?.notifyServerStatus("connected");
      } else {
        startServer(context, port).then(() => {
          sidebarProvider?.notifyServerStatus("connected");
        });
      }
    });
  }

  context.subscriptions.push({ dispose: stopServer });
}

export function deactivate() {
  stopServer();
}

// ---------------------------------------------------------------------------

async function isServerRunning(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${port}/api/health`, (res) => {
      resolve(res.statusCode === 200);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(1500, () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function startServer(
  context: vscode.ExtensionContext,
  port: number
): Promise<void> {
  const config = vscode.workspace.getConfiguration("localAgent");
  const workspaceRoot =
    vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? process.cwd();

  // Resolve python: config override → .venv in active workspace → extension folder fallback
  let python: string = config.get("pythonPath", "");
  if (!python) {
    const workspacePython = path.join(workspaceRoot, ".venv", "bin", "python");
    if (fs.existsSync(workspacePython)) {
      python = workspacePython;
    } else {
      // Extension lives inside axonx/vscode-extension — go up one level
      const agentWorkspace = path.join(context.extensionPath, "..");
      python = path.join(agentWorkspace, ".venv", "bin", "python");
    }
  }

  const agentWorkspace = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? path.join(context.extensionPath, "..");

  return new Promise((resolve) => {
    serverProcess = cp.spawn(
      python,
      ["-m", "agent", "serve", "--workspace", workspaceRoot, "--port", String(port)],
      {
        cwd: agentWorkspace,
        env: { ...process.env },
        stdio: ["ignore", "pipe", "pipe"],
      }
    );

    let started = false;

    const onData = (data: Buffer) => {
      const text = data.toString();
      if (!started && text.includes("Agent server running")) {
        started = true;
        resolve();
      }
    };

    serverProcess.stdout?.on("data", onData);
    serverProcess.stderr?.on("data", onData);

    serverProcess.on("error", (err) => {
      vscode.window.showErrorMessage(`Local Agent: failed to start server — ${err.message}`);
      if (!started) resolve();
    });

    serverProcess.on("exit", (code) => {
      if (!started) resolve();
      sidebarProvider?.notifyServerStatus("disconnected");
    });

    // Fallback: poll until server responds
    const poll = setInterval(async () => {
      if (await isServerRunning(port)) {
        clearInterval(poll);
        if (!started) {
          started = true;
          resolve();
        }
      }
    }, 500);

    // Give up after 30 s
    setTimeout(() => {
      clearInterval(poll);
      if (!started) {
        started = true;
        resolve();
      }
    }, 30_000);
  });
}

function stopServer(): Promise<void> {
  return new Promise((resolve) => {
    if (!serverProcess) {
      resolve();
      return;
    }
    serverProcess.once("exit", () => resolve());
    serverProcess.kill("SIGTERM");
    serverProcess = undefined;
  });
}
