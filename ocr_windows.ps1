# Puente con el OCR integrado de Windows (Windows.Media.Ocr). Lo usa traductor_ocr.py.
# Protocolo por stdin (una línea por petición):
#   IDIOMAS|-            -> {"idiomas":["en-US","es-MX"]}
#   <etiqueta>|<ruta>    -> {"text":"..."}  o  {"error":"..."}     (etiqueta: p. ej. "en-US")
[Console]::InputEncoding  = [Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[void][Windows.Media.Ocr.OcrEngine,           Windows.Media.Ocr,         ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
[void][Windows.Storage.StorageFile,            Windows.Storage,          ContentType=WindowsRuntime]
[void][Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
[void][Windows.Globalization.Language,         Windows.Globalization,    ContentType=WindowsRuntime]

$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) {
    $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    [void]$t.Wait(-1)
    $t.Result
}

while ($null -ne ($line = [Console]::In.ReadLine())) {
    try {
        $partes = $line.Split('|', 2)
        if ($partes[0] -eq 'IDIOMAS') {
            $tags = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })
            (@{ idiomas = $tags } | ConvertTo-Json -Compress)
            continue
        }
        $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($partes[0]))
        if (-not $eng) { (@{ error = 'sin OCR para ' + $partes[0] } | ConvertTo-Json -Compress); continue }
        $file   = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($partes[1])) ([Windows.Storage.StorageFile])
        $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $dec    = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bmp    = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $res    = Await ($eng.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
        $lineas = @($res.Lines | ForEach-Object { $_.Text })
        (@{ text = ($lineas -join "`n") } | ConvertTo-Json -Compress)
    } catch {
        (@{ error = $_.Exception.Message } | ConvertTo-Json -Compress)
    }
}
