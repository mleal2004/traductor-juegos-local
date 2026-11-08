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
        $modo = 'T'
        if ($line.StartsWith('L|')) { $modo = 'L'; $line = $line.Substring(2) }
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
        if ($modo -eq 'L') {
            # cada línea con su rectángulo (unión de los rectángulos de sus palabras)
            $out = New-Object System.Collections.ArrayList
            foreach ($l in $res.Lines) {
                $x0 = [double]::MaxValue; $y0 = [double]::MaxValue; $x1 = 0.0; $y1 = 0.0
                foreach ($w in $l.Words) {
                    $r = $w.BoundingRect
                    if ($r.X -lt $x0) { $x0 = $r.X }; if ($r.Y -lt $y0) { $y0 = $r.Y }
                    if ($r.X + $r.Width -gt $x1) { $x1 = $r.X + $r.Width }; if ($r.Y + $r.Height -gt $y1) { $y1 = $r.Y + $r.Height }
                }
                [void]$out.Add(@{ t = $l.Text; x = [int]$x0; y = [int]$y0; w = [int]($x1 - $x0); h = [int]($y1 - $y0) })
            }
            (@{ lineas = $out.ToArray() } | ConvertTo-Json -Compress -Depth 4)
            continue
        }
        $lineas = @($res.Lines | ForEach-Object { $_.Text })
        (@{ text = ($lineas -join "`n") } | ConvertTo-Json -Compress)
    } catch {
        (@{ error = $_.Exception.Message } | ConvertTo-Json -Compress)
    }
}
