
<?php

header('Content-Type: application/json');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode([
        'status' => 'Error',
        'message' => 'Only POST requests are allowed.'
    ]);
    exit;
}

$contentType = $_SERVER['CONTENT_TYPE'] ?? '';

if (str_contains($contentType, 'application/json')) {

    $data = json_decode(file_get_contents('php://input'), true) ?? [];
} else {

    $data = $_POST;
}

$latitude = $data['latitude'] ?? null;
$longitude = $data['longitude'] ?? null;
$startDate = $data['analysis_start'] ?? '';
$endDate = $data['analysis_end'] ?? '';

if (!is_numeric($latitude) || !is_numeric($longitude)) {
    http_response_code(400);
    echo json_encode([
        'status' => 'Error',
        'message' => 'Valid latitude and longitude are required.'
    ]);
    exit;
}

$latitude = (float) $latitude;
$longitude = (float) $longitude;

if ($latitude < -90 || $latitude > 90 || $longitude < -180 || $longitude > 180) {
    http_response_code(400);
    echo json_encode([
        'status' => 'Error',
        'message' => 'Coordinates are outside the valid range.'
    ]);
    exit;
}

function isValidDateTime($value)
{
    if (!is_string($value)) {
        return false;
    }

    $formats = [
        '!Y-m-d\TH:i',
        '!Y-m-d\TH:i:s'
    ];

    foreach ($formats as $format) {
        $date = DateTimeImmutable::createFromFormat($format, $value);
        $errors = DateTimeImmutable::getLastErrors();

        if (
            $date !== false &&
            ($errors === false || ($errors['warning_count'] === 0 && $errors['error_count'] === 0))
        ) {
            return true;
        }
    }

    return false;
}

if (!isValidDateTime($startDate) || !isValidDateTime($endDate)) {
    http_response_code(400);
    echo json_encode([
        'status' => 'Error',
        'message' => 'Valid analysis start and end dates are required.'
    ]);
    exit;
}

if (new DateTimeImmutable($startDate) >= new DateTimeImmutable($endDate)) {
    http_response_code(400);
    echo json_encode([
        'status' => 'Error',
        'message' => 'The analysis end must be after the analysis start.'
    ]);
    exit;
}

$projectRoot = dirname(__DIR__);

$pythonScript = $projectRoot . DIRECTORY_SEPARATOR .
    'engine' . DIRECTORY_SEPARATOR .
    'calculations' . DIRECTORY_SEPARATOR .
    'calculate_sun_and_earth_positions.py';

$pythonExecutable = 'python';

if (!is_file($pythonScript)) {
    http_response_code(500);
    echo json_encode([
        'status' => 'Error',
        'message' => 'Python calculation script was not found.'
    ]);
    exit;
}

$command = [
    $pythonExecutable,
    $pythonScript,
    '--latitude',
    (string) $latitude,
    '--longitude',
    (string) $longitude,
    '--analysis-start',
    $startDate,
    '--analysis-end',
    $endDate
];

$descriptors = [
    0 => ['pipe', 'r'],
    1 => ['pipe', 'w'],
    2 => ['pipe', 'w']
];

$process = proc_open($command, $descriptors, $pipes);

if (!is_resource($process)) {
    http_response_code(500);
    echo json_encode([
        'status' => 'Error',
        'message' => 'Unable to start the Python calculation engine.'
    ]);
    exit;
}

fclose($pipes[0]);

$output = stream_get_contents($pipes[1]);
fclose($pipes[1]);

$errors = stream_get_contents($pipes[2]);
fclose($pipes[2]);

$exitCode = proc_close($process);

$result = json_decode($output, true);

if (json_last_error() === JSON_ERROR_NONE && is_array($result)) {
    if ($exitCode !== 0) {
        http_response_code(422);
    }

    echo $output;
    exit;
}

http_response_code(500);

echo json_encode([
    'status' => 'Error',
    'message' => 'The Python engine returned an invalid response.',
    'details' => trim($errors),
    'exit_code' => $exitCode
]);
