on run
	set myPOSIXPath to POSIX path of (path to me)
	set AppleScript's text item delimiters to "/Contents/Resources/"
	set pathParts to text items of myPOSIXPath
	set bundlePath to (pathParts as text)
	set AppleScript's text item delimiters to ""
	set repoRoot to do shell script "dirname " & quoted form of bundlePath

	set pythonBin to repoRoot & "/.venv/bin/python"

	do shell script "cd " & quoted form of repoRoot & " && PYTHONUNBUFFERED=1 HF_HUB_DISABLE_XET=1 " & quoted form of pythonBin & " -m laris > /tmp/laris.log 2>&1 &"

	display dialog "LARIS rodando. Segure cmd_r para falar." & return & return & "Log: /tmp/laris.log" & return & "Para parar: pkill -9 -f 'python -m laris'" buttons {"OK"} default button 1 with title "LARIS" giving up after 5
end run
