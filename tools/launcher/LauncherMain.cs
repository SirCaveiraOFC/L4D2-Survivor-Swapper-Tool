using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("L4D2 Survivor Swapper Tool")]
[assembly: AssemblyDescription("Automated L4D2 survivor skin converter and workshop hub")]
[assembly: AssemblyProduct("L4D2 Survivor Swapper Tool")]
[assembly: AssemblyCompany("Sr.Caveira")]
[assembly: AssemblyCopyright("Copyright (c) 2024-2026 Sr.Caveira")]
[assembly: AssemblyVersion("2.1.0.0")]
[assembly: AssemblyFileVersion("2.1.0.0")]

namespace L4D2SurvivorSwapperLauncher
{
    internal static class Program
    {
        private const int ATTACH_PARENT_PROCESS = -1;

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AttachConsole(int dwProcessId);

        [STAThread]
        private static int Main(string[] args)
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string appPy = Path.Combine(baseDir, "app.py");
            if (!File.Exists(appPy))
            {
                MessageBox.Show(
                    "Could not find app.py alongside L4D2 Survivor Swapper Tool.exe.\n\n"
                        + "Make sure you extracted the entire folder before launching.",
                    "L4D2 Survivor Swapper Tool",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return 1;
            }

            bool isCli = WantsConsole(args);
            bool usingBundledRuntime;
            string runnerExe = ResolvePythonExecutable(baseDir, isCli, out usingBundledRuntime);
            if (string.IsNullOrEmpty(runnerExe))
            {
                MessageBox.Show(
                    "Embedded runtime folder ('runtime\\') was not found and no Python 3.10+ installation was detected in PATH.\n\n"
                        + "If you downloaded the source code instead of the Portable release, install Python 3.10+ and run _INSTALL_REQUIREMENTS.bat.",
                    "L4D2 Survivor Swapper Tool",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return 1;
            }

            var psi = new ProcessStartInfo
            {
                FileName = runnerExe,
                Arguments = BuildArguments(appPy, runnerExe, args),
                WorkingDirectory = baseDir.TrimEnd('\\'),
                UseShellExecute = false,
                CreateNoWindow = !isCli
            };

            psi.EnvironmentVariables["PYTHONUTF8"] = "1";
            if (usingBundledRuntime)
            {
                psi.EnvironmentVariables.Remove("PYTHONPATH");
                psi.EnvironmentVariables.Remove("PYTHONHOME");
                psi.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
            }

            if (isCli)
            {
                AttachConsole(ATTACH_PARENT_PROCESS);
            }

            try
            {
                Process proc = Process.Start(psi);
                if (proc == null)
                {
                    MessageBox.Show(
                        "Failed to start Python runtime process.",
                        "L4D2 Survivor Swapper Tool",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error
                    );
                    return 1;
                }

                if (isCli)
                {
                    proc.WaitForExit();
                    return proc.ExitCode;
                }
                return 0;
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    "Failed to launch L4D2 Survivor Swapper Tool:\n\n" + ex.Message,
                    "L4D2 Survivor Swapper Tool",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return 1;
            }
        }

        private static bool WantsConsole(string[] args)
        {
            if (args == null || args.Length == 0)
            {
                return false;
            }
            for (int i = 0; i < args.Length; i++)
            {
                string a = (args[i] ?? string.Empty).Trim().ToLowerInvariant();
                if (a == "--cli"
                    || a == "--check-env"
                    || a == "--apply-crowbar-settings"
                    || a == "-h"
                    || a == "--help")
                {
                    return true;
                }
            }
            return false;
        }

        private static string ResolvePythonExecutable(string baseDir, bool isCli, out bool usingBundled)
        {
            string runtimeDir = Path.Combine(baseDir, "runtime");
            if (Directory.Exists(runtimeDir))
            {
                string preferred = Path.Combine(runtimeDir, isCli ? "python.exe" : "pythonw.exe");
                if (File.Exists(preferred))
                {
                    usingBundled = true;
                    return preferred;
                }
                string fallback = Path.Combine(runtimeDir, "python.exe");
                if (File.Exists(fallback))
                {
                    usingBundled = true;
                    return fallback;
                }
            }

            usingBundled = false;
            string[] candidates = isCli
                ? new[] { "python.exe", "py.exe" }
                : new[] { "pythonw.exe", "pyw.exe", "python.exe", "py.exe" };

            for (int i = 0; i < candidates.Length; i++)
            {
                string found = FindOnPath(candidates[i]);
                if (!string.IsNullOrEmpty(found))
                {
                    return found;
                }
            }
            return null;
        }

        private static string FindOnPath(string fileName)
        {
            string pathEnv = Environment.GetEnvironmentVariable("PATH") ?? string.Empty;
            string[] parts = pathEnv.Split(new[] { ';' }, StringSplitOptions.RemoveEmptyEntries);
            for (int i = 0; i < parts.Length; i++)
            {
                string dir = parts[i].Trim().Trim('"');
                if (string.IsNullOrEmpty(dir))
                {
                    continue;
                }
                try
                {
                    string candidate = Path.Combine(dir, fileName);
                    if (File.Exists(candidate))
                    {
                        return candidate;
                    }
                }
                catch
                {
                }
            }
            return null;
        }

        private static string BuildArguments(string appPy, string runnerExe, string[] args)
        {
            var sb = new StringBuilder();
            string exeName = Path.GetFileName(runnerExe).ToLowerInvariant();
            if (exeName == "py.exe" || exeName == "pyw.exe")
            {
                sb.Append("-3 ");
            }
            sb.Append(QuoteArg(appPy));
            if (args != null)
            {
                for (int i = 0; i < args.Length; i++)
                {
                    sb.Append(' ').Append(QuoteArg(args[i] ?? string.Empty));
                }
            }
            return sb.ToString();
        }

        private static string QuoteArg(string value)
        {
            if (value.Length == 0)
            {
                return "\"\"";
            }
            bool needsQuotes = false;
            for (int i = 0; i < value.Length; i++)
            {
                char c = value[i];
                if (c == ' ' || c == '\t' || c == '"')
                {
                    needsQuotes = true;
                    break;
                }
            }
            if (!needsQuotes)
            {
                return value;
            }
            var sb = new StringBuilder();
            sb.Append('"');
            int backslashes = 0;
            for (int i = 0; i < value.Length; i++)
            {
                char c = value[i];
                if (c == '\\')
                {
                    backslashes++;
                }
                else if (c == '"')
                {
                    sb.Append('\\', backslashes * 2 + 1);
                    sb.Append('"');
                    backslashes = 0;
                }
                else
                {
                    if (backslashes > 0)
                    {
                        sb.Append('\\', backslashes);
                        backslashes = 0;
                    }
                    sb.Append(c);
                }
            }
            if (backslashes > 0)
            {
                sb.Append('\\', backslashes * 2);
            }
            sb.Append('"');
            return sb.ToString();
        }
    }
}
