On Error Resume Next
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
q = Chr(34)
py = folder & "\..\deps\venv\Scripts\python.exe"
logf = folder & "\logs\astrbot.log"
inner = q & py & q & " " & q & folder & "\astrbot_entry.py" & q & " >> " & q & logf & q & " 2>&1"
sh.CurrentDirectory = folder & "\..\deps\astrbot-home"
sh.Run "cmd /c " & q & inner & q, 0, False
If Err.Number <> 0 Then
  fso.OpenTextFile(folder & "\logs\startup-error.log", 8, True).WriteLine CStr(Now) & "  " & Err.Number & "  " & Err.Description
End If
