"""Скрипты PowerShell для озвучки через голоса Windows (используются в voice.py).

Строки здесь длиннее 79 символов: это код PowerShell внутри строк Python,
переносить его без проверки на Windows рискованно. Для этого файла правило
длины строки отключено в pyproject.toml и .flake8.

Подстановки: __TEXT__, __VOICE__, __RATE__, __VOL__, __SAPIRATE__, __SAPIVOL__.
"""

ONECORE_PS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$s = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$all = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices
$v = $all | Where-Object { $_.DisplayName -eq '__VOICE__' } | Select-Object -First 1
if (-not $v) { $v = $all | Where-Object { $_.Language -like 'ru*' } | Select-Object -First 1 }
if (-not $v) { exit 3 }
$s.Voice = $v
try { $s.Options.SpeakingRate = __RATE__; $s.Options.AudioVolume = __VOL__ } catch {}
$op = $s.SynthesizeTextToStreamAsync('__TEXT__')
$task = $asTask.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream]).Invoke($null, @($op))
$task.Wait(-1) | Out-Null
$stream = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($task.Result)
$ms = New-Object System.IO.MemoryStream
$stream.CopyTo($ms)
$ms.Position = 0
(New-Object System.Media.SoundPlayer $ms).PlaySync()
"""

SAPI_PS = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$all = $s.GetInstalledVoices() | Where-Object { $_.Enabled }
$v = $all | Where-Object { $_.VoiceInfo.Name -eq '__VOICE__' } | Select-Object -First 1
if (-not $v) { $v = $all | Where-Object { $_.VoiceInfo.Culture.Name -like 'ru*' } | Select-Object -First 1 }
if (-not $v) { exit 3 }
$s.SelectVoice($v.VoiceInfo.Name)
$s.Rate = __SAPIRATE__
$s.Volume = __SAPIVOL__
$s.Speak('__TEXT__')
"""

LIST_PS = r"""
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
  [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | ForEach-Object { "ONECORE|$($_.Language)|$($_.DisplayName)" }
} catch {}
try {
  Add-Type -AssemblyName System.Speech
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { "SAPI|$($_.VoiceInfo.Culture.Name)|$($_.VoiceInfo.Name)" }
} catch {}
"""
