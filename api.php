<?php
header("Access-Control-Allow-Origin: *");
header("Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS");
header("Access-Control-Allow-Headers: Content-Type");
header('Content-Type: application/json');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit();
}

$action = $_GET['action'] ?? '';

// 1. ดึงข้อมูลสถานะจาก run.py (/api/status)
if ($action === 'get_status') {
    $ctx = stream_context_create([
        'http' => [
            'method'  => 'GET',
            'timeout' => 3
        ]
    ]);
    
    $pyDataRaw = @file_get_contents('http://127.0.0.1:5000/api/status', false, $ctx);
    if ($pyDataRaw !== false) {
        $pyData = json_decode($pyDataRaw, true);
        
        // แปลง active_records ให้ตรงกับโครงสร้างที่หน้าเว็บ UI รอรับ
        $activeList = [];
        foreach ($pyData['active_records'] ?? [] as $rec) {
            $activeList[] = [
                'username' => $rec['username'] ?? '',
                'elapsed' => $rec['elapsed'] ?? 0,
                'platform' => $rec['platform'] ?? 'TikTok'
            ];
        }

        $watchlist = json_decode(@file_get_contents(__DIR__ . '/watchlist.json'), true) ?? [];

        echo json_encode([
            'active_count' => count($activeList),
            'active_list' => $activeList,
            'watchlist_count' => $pyData['watchlist_count'] ?? count($watchlist),
            'total_recordings' => $pyData['total_recordings'] ?? 0,
            'watchlist' => array_values($watchlist)
        ]);
    } else {
        $watchlist = json_decode(@file_get_contents(__DIR__ . '/watchlist.json'), true) ?? [];
        echo json_encode([
            'active_count' => 0,
            'active_list' => [],
            'watchlist_count' => count($watchlist),
            'total_recordings' => 0,
            'watchlist' => array_values($watchlist)
        ]);
    }
    exit();
}

// 2. เพิ่มเข้า Watchlist
if ($action === 'add_watchlist' && $_SERVER['REQUEST_METHOD'] === 'POST') {
    $user = trim($_POST['username'] ?? '');
    if ($user) {
        $payload = json_encode(['username' => $user]);
        $ctx = stream_context_create([
            'http' => [
                'method'  => 'POST',
                'header'  => "Content-Type: application/json\r\n",
                'content' => $payload,
                'timeout' => 3
            ]
        ]);
        @file_get_contents('http://127.0.0.1:5000/api/watchlist', false, $ctx);
    }
    echo json_encode(['status' => 'ok']);
    exit();
}

// 3. ลบออก จาก Watchlist
if ($action === 'remove_watchlist' && $_SERVER['REQUEST_METHOD'] === 'POST') {
    $user = trim($_POST['username'] ?? '');
    if ($user) {
        $payload = json_encode(['username' => $user]);
        $ctx = stream_context_create([
            'http' => [
                'method'  => 'DELETE',
                'header'  => "Content-Type: application/json\r\n",
                'content' => $payload,
                'timeout' => 3
            ]
        ]);
        @file_get_contents('http://127.0.0.1:5000/api/watchlist', false, $ctx);
    }
    echo json_encode(['status' => 'ok']);
    exit();
}

echo json_encode(['error' => 'Invalid action']);
