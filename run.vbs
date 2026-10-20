' Launch DeskIsle without a console window.
' Resolves pythonw.exe relative to this file so the script stays portable.
Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

' Prefer a local virtual environment, then fall back to pythonw.exe on PATH.
pythonw = ""
For Each candidate in Array("venv\Scripts\pythonw.exe", ".venv\Scripts\pythonw.exe")
    path = fso.BuildPath(scriptDir, candidate)
    If fso.FileExists(path) Then
        pythonw = path
        Exit For
    End If
Next

command = "pythonw.exe"
If pythonw <> "" Then command = """" & pythonw & """"
WshShell.Run command & " main.py", 0, False
