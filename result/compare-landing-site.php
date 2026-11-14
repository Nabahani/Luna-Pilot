<?php

header('Content-Type: application/json');

$comparisonData = json_decode(file_get_contents('php://input'), true);

$descriptors = [
    0 => ['pipe', 'r'],
    1 => ['pipe', 'w'],
    2 => ['pipe', 'w'],
];

$process = proc_open(
    ['python', '../api/main.py'],
    $descriptors,
    $pipes
);

$output = null;
$errors = null;
$status = null;

if (is_resource($process)) {

    fwrite($pipes[0], $jsonData . "\n");
    fclose($pipes[0]);

    $output = stream_get_contents($pipes[1]);
    fclose($pipes[1]);

    $errors = stream_get_contents($pipes[2]);
    fclose($pipes[2]);

    $status = proc_close($process);
}

if ($status === 0) {
    echo $output;
} else {
    http_response_code(500);

    echo json_encode([
        'status' => 'error',
        'message' => $errors,
        'exit_code' => $status
    ]);
}
