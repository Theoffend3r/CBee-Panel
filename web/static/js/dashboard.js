console.log('🐝 CBee Panel loaded');

function getToken() {
    return localStorage.getItem('token');
}

async function apiRequest(url, options = {}) {
    const token = getToken();
    const headers = {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        ...(options.headers || {})
    };
    const response = await fetch(url, { ...options, headers });
    if (response.status === 401) {
        localStorage.removeItem('token');
        window.location.href = '/login';
        return null;
    }
    return response;
}

async function loadInbounds(filter = 'all') {
    try {
        const res = await apiRequest('/api/admin/inbounds');
        if (!res) return;
        const data = await res.json();
        let items = data.inbounds || [];
        if (filter !== 'all') {
            items = items.filter(i => i.protocol === filter);
        }
        const container = document.getElementById('inboundItems');
        if (!container) return;
        if (items.length === 0) {
            container.innerHTML = '<p style="color:#888;text-align:center;padding:20px;">هیچ اینباندی یافت نشد</p>';
            return;
        }
        let html = '<table><tr><th>پروتکل</th><th>پورت</th><th>ترابری</th><th>TLS</th><th>وضعیت</th><th>مصرف</th><th>عملیات</th></tr>';
        for (const i of items) {
            const status = i.enabled ? '✅ فعال' : '❌ غیرفعال';
            const tlsStatus = i.tls ? '🔒 فعال' : '🔓 غیرفعال';
            const used = i.used_bytes || 0;
            const total = i.total_bytes || 0;
            let usage = (used / 1024 / 1024).toFixed(1) + ' MB';
            if (total > 0) {
                const pct = (used / total * 100).toFixed(1);
                usage += ` / ${(total / 1024 / 1024 / 1024).toFixed(1)} GB (${pct}%)`;
            }
            html += `<tr>
                <td><strong>${i.protocol.toUpperCase()}</strong></td>
                <td>${i.port}</td>
                <td>${i.transport || 'websocket'}</td>
                <td>${tlsStatus}</td>
                <td>${status}</td>
                <td>${usage}</td>
                <td>
                    <button onclick="toggleInbound('${i.id}')" style="background:${i.enabled ? '#e74c3c' : '#2ecc71'};color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;margin-right:5px;">
                        ${i.enabled ? 'غیرفعال' : 'فعال'}
                    </button>
                    <button onclick="deleteInbound('${i.id}')" style="background:#e74c3c;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;">
                        حذف
                    </button>
                </td>
            </tr>`;
        }
        html += '</table>';
        container.innerHTML = html;
    } catch(e) {
        console.error('Error loading inbounds:', e);
    }
}

async function toggleInbound(id) {
    try {
        const res = await apiRequest(`/api/admin/inbound/${id}`, {
            method: 'PUT',
            body: JSON.stringify({ enabled: false })
        });
        if (res && res.ok) {
            loadInbounds(document.querySelector('.hex-card.active')?.textContent?.toLowerCase() || 'all');
        }
    } catch(e) {
        console.error('Error toggling inbound:', e);
    }
}

async function deleteInbound(id) {
    if (!confirm('آیا از حذف این اینباند مطمئن هستید؟')) return;
    try {
        const res = await apiRequest(`/api/admin/inbound/${id}`, {
            method: 'DELETE'
        });
        if (res && res.ok) {
            loadInbounds(document.querySelector('.hex-card.active')?.textContent?.toLowerCase() || 'all');
        }
    } catch(e) {
        console.error('Error deleting inbound:', e);
    }
}

async function loadStats() {
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        document.getElementById('activeConns').textContent = data.active_connections || 0;
        const total = data.total_bytes || 0;
        if (total > 1024*1024*1024) {
            document.getElementById('totalBytes').textContent = (total/1024/1024/1024).toFixed(2) + ' GB';
        } else if (total > 1024*1024) {
            document.getElementById('totalBytes').textContent = (total/1024/1024).toFixed(2) + ' MB';
        } else {
            document.getElementById('totalBytes').textContent = (total/1024).toFixed(2) + ' KB';
        }
        document.getElementById('totalReqs').textContent = data.total_requests || 0;
    } catch(e) {
        console.error('Error loading stats:', e);
    }
}

function filterProtocol(protocol) {
    document.querySelectorAll('.hex-card').forEach(c => c.classList.remove('active'));
    const cards = document.querySelectorAll('.hex-card');
    cards.forEach(c => {
        if (c.textContent.toLowerCase().includes(protocol) || protocol === 'all') {
            c.classList.add('active');
        }
    });
    loadInbounds(protocol);
}

function logout() {
    localStorage.removeItem('token');
    window.location.href = '/login';
}

document.addEventListener('DOMContentLoaded', function() {
    loadStats();
    loadInbounds('all');
    setInterval(loadStats, 5000);
});
