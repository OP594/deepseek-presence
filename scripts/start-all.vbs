On Error Resume Next
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
q = Chr(34)
target = q & folder & "\start-all.bat" & q
Set sh = CreateObject("WScript.Shell")
sh.Run target, 0, False
If Err.Number <> 0 Then
  fso.OpenTextFile(folder & "\startup-error.log", 8, True).WriteLine CStr(Now) & "  " & Err.Number & "  " & Err.Description
End If
