using System;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Diagnostics;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;

internal static class LocalSetup {
    [STAThread] static void Main(string[] args) {
        if(args.Length==2 && args[0]=="--extract-only") {
            try { Extract(Path.GetFullPath(args[1])); Environment.Exit(0); }
            catch { Environment.Exit(1); }
            return;
        }
        Application.EnableVisualStyles();
        var form=new Form {Text="Self Agent 安装",Width=560,Height=230,StartPosition=FormStartPosition.CenterScreen,MaximizeBox=false};
        form.Font=new Font("Microsoft YaHei",10);
        var label=new Label {Text="正在安装本机长期知识库…",Left=28,Top=30,Width=490,Height=100};form.Controls.Add(label);
        form.Shown+=async (sender,e)=>{
            try {
                await Task.Run(()=>{
                    string root=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"self-agent","apps","local-0.2.0-RELEASE_ID");
                    if(!File.Exists(Path.Combine(root,"manifest.json")))Extract(root);
                    var start=new ProcessStartInfo(Path.Combine(root,"pythonw.exe"),"\""+Path.Combine(root,"source","scripts","setup_local.py")+"\"") {
                        UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden,
                        RedirectStandardOutput=true,RedirectStandardError=true,WorkingDirectory=root
                    };
                    using(var process=Process.Start(start)) {
                        var stdout=process.StandardOutput.ReadToEndAsync();var stderr=process.StandardError.ReadToEndAsync();
                        if(!process.WaitForExit(360000))throw new Exception("setup_timeout");
                        Task.WaitAll(stdout,stderr);
                        if(process.ExitCode!=0)throw new Exception("setup_failed");
                    }
                    // Optional management shortcut; normal memory use needs no open window.
                    string menu=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),"Programs","Self Agent.url");
                    string launcher=Path.Combine(root,"source","scripts","open_local.py");
                    // Use a real shell shortcut so the target stays a hidden pythonw process.
                    Type t=Type.GetTypeFromProgID("WScript.Shell");
                    dynamic shell=Activator.CreateInstance(t);
                    dynamic shortcut=shell.CreateShortcut(Path.ChangeExtension(menu,".lnk"));
                    shortcut.TargetPath=Path.Combine(root,"pythonw.exe");shortcut.Arguments="\""+launcher+"\"";shortcut.WorkingDirectory=root;shortcut.Save();
                });
                label.Text="安装完成。\n请重开智能体会话；Codex 首次需在 /hooks 中审核并信任 Self Agent。\n之后正常聊天即可自动使用记忆。";
            } catch {
                label.Text="安装未完成，原有数据已保留。\n请查看本机 self-agent\\local\\setup-result.json，或将安装问题交给智能体处理。";
            }
        };
        Application.Run(form);
    }
    static void Extract(string root) {
        Directory.CreateDirectory(root);
        using(var verify=Assembly.GetExecutingAssembly().GetManifestResourceStream("bundle.zip"))using(var sha=SHA256.Create()) {
            if(BitConverter.ToString(sha.ComputeHash(verify)).Replace("-","").ToLowerInvariant()!="BUNDLE_SHA256")throw new Exception("bundle_checksum_mismatch");
        }
        string prefix=Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
        using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("bundle.zip"))
        using(var zip=new ZipArchive(stream,ZipArchiveMode.Read)) {
            foreach(var entry in zip.Entries) {
                string path=Path.GetFullPath(Path.Combine(root,entry.FullName));
                if(!path.StartsWith(prefix,StringComparison.OrdinalIgnoreCase))throw new Exception("invalid_archive_path");
                if(entry.FullName.EndsWith("/")){Directory.CreateDirectory(path);continue;}
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                using(var input=entry.Open())using(var output=new FileStream(path,FileMode.Create,FileAccess.Write,FileShare.None))input.CopyTo(output);
            }
        }
    }
}
