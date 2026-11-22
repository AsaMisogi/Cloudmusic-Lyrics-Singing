// Windows 自带 .NET Framework：更新器不加载安装目录里的 Python/Qt，主程序退出后仍能工作。
using System;
using System.IO;
using System.IO.Compression;
using System.Diagnostics;
using System.Reflection;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Collections.Generic;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;
using System.Web.Script.Serialization;
using System.Runtime.InteropServices;

internal static class UpdateHelper {
    const string Product = "utatomo/windows-x64/1";
    static readonly string[] Roots = { "_internal", "docs", "THIRD-PARTY-LICENSES", "LICENSE", "THIRD-PARTY.md", "README.md", "Utatomo.exe" };
    static readonly string Self = Assembly.GetExecutingAssembly().Location;
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 4 * 1024 * 1024 };
    public sealed class Manifest {
        public string product { get; set; }
        public string version { get; set; }
        public string baseVersion { get; set; }
        public string baseExe { get; set; }
        public Dictionary<string,string> files { get; set; }
    }
    sealed class BaseMismatch : IOException { public BaseMismatch(string s) : base(s) {} }

    // 公钥作为编译资源固定在本机助手中。镜像只参与传输，不能决定可以安装哪些字节。
    static byte[] Verify(string envelope) {
        var obj = Json.Deserialize<Dictionary<string,string>>(envelope);
        byte[] payload = Convert.FromBase64String(obj["payload"]);
        byte[] signature = Convert.FromBase64String(obj["signature"]);
        using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("signer"))
        using (var mem = new MemoryStream()) {
            stream.CopyTo(mem);
            using (var cert = new X509Certificate2(mem.ToArray()))
            using (var key = cert.GetRSAPublicKey())
                if (!key.VerifyData(payload, signature, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1))
                    throw new InvalidDataException("发行签名不正确。");
        }
        return payload;
    }
    static bool Safe(string name) {
        string[] parts = name.Split('/');
        if (Array.IndexOf(Roots, parts[0]) < 0 || (Array.IndexOf(Roots, parts[0]) < 3) != (parts.Length > 1)) return false;
        foreach (string p in parts)
            if (p.Length == 0 || p.EndsWith(" ") || p.EndsWith(".") || p.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 ||
                Regex.IsMatch(p, @"^(con|nul|prn|aux|com[1-9¹²³]|lpt[1-9¹²³])(\.|$)", RegexOptions.IgnoreCase)) return false;
        return true;
    }
    static Manifest ReadManifest(string envelope) {
        var m = Json.Deserialize<Manifest>(Encoding.UTF8.GetString(Verify(envelope)));
        if (m.product != Product || !Regex.IsMatch(m.version, @"^\d+\.\d+\.\d+$") || m.files == null ||
            !m.files.ContainsKey("Utatomo.exe") || !m.files.ContainsKey("_internal/update/Utatomo-Update.exe"))
            throw new InvalidDataException("不是完整的咏伴 Windows 发行清单。");
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var kv in m.files)
            if (!Safe(kv.Key) || !names.Add(kv.Key) || !Regex.IsMatch(kv.Value, "^[a-f0-9]{64}$"))
                throw new InvalidDataException("发行清单的文件名或摘要无效。");
        return m;
    }
    static string Hash(string path) {
        using (var f = File.OpenRead(path)) using (var sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(f)).Replace("-", "").ToLowerInvariant();
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern bool CreateHardLink(string newName, string existing, IntPtr reserved);

    // 先在同卷 next/ 组装签名清单指定的完整目录。只有完全校验通过才允许交接；
    // 新版不再发布的文件自然不会进入 next，data/ 等用户目录永远不在切换列表。
    static void Stage(string root, string job, Manifest m, bool full, ZipArchive archive, string loose) {
        if (!full && Hash(Path.Combine(root, "Utatomo.exe")) != m.baseExe)
            throw new BaseMismatch("当前程序不是此补丁对应的正式版。");
        string stage = Path.Combine(job, "next");
        if (Directory.Exists(stage)) throw new IOException("暂存目录已存在。");
        Directory.CreateDirectory(stage);
        foreach (var kv in m.files) {
            string dest = Path.Combine(stage, kv.Key);
            Directory.CreateDirectory(Path.GetDirectoryName(dest));
            var e = archive == null ? null : archive.GetEntry("Utatomo/" + kv.Key);
            string local = loose == null ? null : Path.Combine(loose, "Utatomo", kv.Key);
            bool reuse = false;
            if (e != null) {
                using (var s = e.Open()) using (var d = File.Create(dest)) s.CopyTo(d);
            } else if (local != null && File.Exists(local)) {
                File.Copy(local, dest);
            } else {
                if (full) throw new InvalidDataException("完整包缺少文件：" + kv.Key);
                string original = Path.Combine(root, kv.Key);
                if (!File.Exists(original)) throw new BaseMismatch("本机缺少文件：" + kv.Key);
                if (!CreateHardLink(dest, original, IntPtr.Zero)) File.Copy(original, dest);
                reuse = true;
            }
            if (Hash(dest) != kv.Value) {
                if (reuse) throw new BaseMismatch("本机文件已改变：" + kv.Key);
                throw new InvalidDataException("补丁文件校验失败：" + kv.Key);
            }
        }
        File.WriteAllText(Path.Combine(job, "version"), m.version);
    }

    static void Move(string src, string dest) {
        for (int i = 0; ; i++) {
            try {
                if (Directory.Exists(src)) Directory.Move(src, dest); else File.Move(src, dest);
                return;
            } catch (IOException) { if (i == 8) throw; Thread.Sleep(250); }
        }
    }
    static Process Launch(string root, string args) {
        var info = new ProcessStartInfo(Path.Combine(root,"Utatomo.exe"),args) {WorkingDirectory=root, UseShellExecute=false};
        info.EnvironmentVariables["PYINSTALLER_RESET_ENVIRONMENT"] = "1";
        return Process.Start(info);
    }
    static void Apply(string job, int parent) {
        if (parent != 0) {
            Process p = null;
            try { p = Process.GetProcessById(parent); } catch (ArgumentException) {}
            if (p != null) using (p) if (!p.WaitForExit(90000)) throw new IOException("咏伴尚未退出，未替换程序。");
        }
        string root = Path.GetDirectoryName(job), stage = Path.Combine(job, "next"), old = Path.Combine(job, "previous");
        string tag = Path.GetFileName(job);
        if (!Regex.IsMatch(tag, @"^\.utatomo-update-[a-zA-Z0-9_-]+$") || Directory.Exists(old))
            throw new IOException("更新目录无效或已使用。");
        var saved = new List<string>(); var installed = new List<string>();
        Directory.CreateDirectory(old);
        try {
            foreach (string n in Roots) {
                string live = Path.Combine(root,n);
                if (File.Exists(live) || Directory.Exists(live)) { Move(live,Path.Combine(old,n)); saved.Add(n); }
                Move(Path.Combine(stage,n),live); installed.Add(n);
            }
            using (Process child = Launch(root, "--updated " + tag)) {
                string ack = Path.Combine(job, "started"), expected = File.ReadAllText(Path.Combine(job, "version"));
                for (int i = 0; i < 900; i++) {
                    if (File.Exists(ack) && File.ReadAllText(ack) == expected) return;
                    if (child.WaitForExit(100)) throw new IOException("新版在界面就绪前退出。");
                }
                // 仍活着的客户端可能被安全软件暂挂；不结束用户进程，不在运行中覆盖文件。
                File.WriteAllText(Path.Combine(job,"update-error.txt"), "未收到界面就绪回执。旧版已保存在 previous。");
            }
        } catch (Exception cause) {
            installed.Reverse(); saved.Reverse();
            foreach (string n in installed) Move(Path.Combine(root,n), Path.Combine(stage,n));
            foreach (string n in saved) Move(Path.Combine(old,n), Path.Combine(root,n));
            if (parent != 0 && File.Exists(Path.Combine(root,"Utatomo.exe"))) Launch(root, "");
            throw new IOException("已恢复旧版。"+cause.Message, cause);
        }
    }

    // 0.8.3 没有应用内安装入口。解压小补丁后，使用同一个组装器选择旧 EXE；
    // 基线 EXE 和复用文件须与正式包匹配，禁止把差分目录自身当成安装目录。
    static void Bootstrap() {
        string loose = Path.GetDirectoryName(Self);
        Manifest m = ReadManifest(File.ReadAllText(Path.Combine(loose,"target.json")));
        using (var dlg = new OpenFileDialog {Title="请选择已经退出的咏伴 " + m.baseVersion + " 的 Utatomo.exe", Filter="咏伴|Utatomo.exe"}) {
            if (dlg.ShowDialog() != DialogResult.OK) return;
            string root = Path.GetDirectoryName(dlg.FileName);
            if (MessageBox.Show("请先从托盘退出咏伴，再将 " + root + " 更新至 " + m.version + "。个人曲库与设置保留。", "安装咏伴补丁", MessageBoxButtons.OKCancel) != DialogResult.OK) return;
            string job = Path.Combine(root,".utatomo-update-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(job);
            try { Stage(root, job, m, false, null, loose); }
            catch { Directory.Delete(job,true); throw; }
            Apply(job,0);
        }
    }
    [STAThread]
    static int Main(string[] args) {
        AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling", false);
        AppContext.SetSwitch("Switch.System.IO.BlockLongPaths", false);
        try {
            if (args.Length == 0) { Bootstrap(); return 0; }
            if (args[0] == "verify" && args.Length == 1) {
                var input = Console.OpenStandardInput();
                string envelope = new StreamReader(input, Encoding.UTF8).ReadToEnd();
                var bytes = Verify(envelope);
                Console.OpenStandardOutput().Write(bytes,0,bytes.Length);
            } else if (args[0] == "prepare" && args.Length == 3) {
                string job = Path.GetFullPath(args[1]);
                var m = ReadManifest(File.ReadAllText(Path.Combine(job, "update.json")));
                using (var zip = ZipFile.OpenRead(Path.Combine(job,"package.zip")))
                    Stage(Path.GetDirectoryName(job), job, m, args[2] == "full", zip, null);
            } else if (args[0] == "apply" && args.Length == 2) {
                Apply(Path.GetDirectoryName(Self), int.Parse(args[1]));
            } else throw new ArgumentException("未知更新操作。");
            return 0;
        } catch (Exception e) {
            if (args.Length == 0 || args[0] == "apply") {
                if (args.Length > 0) File.WriteAllText(Path.Combine(Path.GetDirectoryName(Self),"update-error.txt"),e.Message);
                MessageBox.Show(e.Message,"咏伴更新未完成",MessageBoxButtons.OK,MessageBoxIcon.Warning);
            } else {
                var b = Encoding.UTF8.GetBytes(e.Message); Console.OpenStandardError().Write(b,0,b.Length);
            }
            return e is BaseMismatch ? 3 : 1;
        }
    }
}
