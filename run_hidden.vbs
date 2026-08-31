' 排程器叫呢個：靜默（冇黑框）跑 run.bat
Dim fso, here, sh
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = here
sh.Run "cmd /c """ & here & "\run.bat""", 0, False
