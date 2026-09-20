function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
}

const csrftoken = getCookie('csrftoken');

function openModal(id) {
  document.getElementById(id).classList.add('open');
}
function closeModal(id) {
  document.getElementById(id).classList.remove('open');
}

// ---------------------------------------------------------------------
// Theme (dark / light)
// ---------------------------------------------------------------------

function getTheme() {
  try { return localStorage.getItem('scloud-theme') || 'dark'; } catch (e) { return 'dark'; }
}

function applyThemeColorMeta(theme) {
  const meta = document.getElementById('theme-color-meta');
  if (meta) meta.setAttribute('content', theme === 'light' ? '#f5f5f7' : '#000000');
}

function toggleTheme() {
  const next = getTheme() === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  applyThemeColorMeta(next);
  try { localStorage.setItem('scloud-theme', next); } catch (e) {}
  document.querySelectorAll('.theme-toggle-icon').forEach((el) => {
    el.textContent = next === 'dark' ? '☀️' : '🌙';
  });
}

document.addEventListener('DOMContentLoaded', () => {
  applyThemeColorMeta(getTheme());
  document.querySelectorAll('.theme-toggle-icon').forEach((el) => {
    el.textContent = getTheme() === 'dark' ? '☀️' : '🌙';
  });
});

// ---------------------------------------------------------------------
// Logout confirmation
// ---------------------------------------------------------------------

function confirmLogout(url) {
  if (confirm('Are you sure you want to sign out?')) {
    window.location = url;
  }
  return false;
}

// ---------------------------------------------------------------------
// Copy share link
// ---------------------------------------------------------------------

function copyLink(elementId, btn) {
  const text = document.getElementById(elementId).textContent.trim();
  const done = () => {
    if (btn) {
      const original = btn.textContent;
      btn.textContent = 'Copied!';
      setTimeout(() => { btn.textContent = original; }, 1500);
    }
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
  } else {
    fallbackCopy(text, done);
  }
}

function fallbackCopy(text, done) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); } catch (e) {}
  ta.remove();
  if (done) done();
}

// ---------------------------------------------------------------------
// Upload - chunked, resumable-per-chunk, so a dropped mobile connection
// only has to retry one small piece instead of restarting a multi-GB file.
// ---------------------------------------------------------------------

function startUpload(input, space, groupId, folderId) {
  uploadFileList(Array.from(input.files), {
    space, groupId, folderId,
    uploadUrl: window.SCLOUD_UPLOAD_URL,
    chunkUrl: window.SCLOUD_UPLOAD_CHUNK_URL,
  });
  input.value = '';
}

function sharedStartUpload(input) {
  uploadFileList(Array.from(input.files), {
    uploadUrl: window.SCLOUD_UPLOAD_URL,
    chunkUrl: window.SCLOUD_UPLOAD_CHUNK_URL,
  });
  input.value = '';
}

async function uploadFileList(files, opts) {
  if (!files.length) return;
  const bar = document.getElementById('upload-progress');
  const fill = bar ? bar.querySelector('.fill') : null;
  if (bar) bar.style.display = 'block';

  const totalBytes = files.reduce((s, f) => s + f.size, 0) || 1;
  let doneBytes = 0;
  const failed = [];

  for (const file of files) {
    try {
      await uploadSingleFile(file, opts, (loaded) => {
        if (fill) fill.style.width = Math.round(((doneBytes + loaded) / totalBytes) * 100) + '%';
      });
    } catch (e) {
      failed.push(file.name);
    }
    doneBytes += file.size;
  }

  if (failed.length) {
    alert(`Failed to upload: ${failed.join(', ')}`);
  }
  window.location.reload();
}

function uploadSingleFile(file, opts, onProgress) {
  const chunkSize = window.SCLOUD_CHUNK_SIZE || (8 * 1024 * 1024);
  if (file.size <= chunkSize) {
    return simpleUpload(file, opts, onProgress);
  }
  return chunkedUpload(file, opts, onProgress);
}

function simpleUpload(file, opts, onProgress) {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    if (opts.space) fd.append('space', opts.space);
    if (opts.groupId) fd.append('group_id', opts.groupId);
    if (opts.folderId) fd.append('folder_id', opts.folderId);
    fd.append('files', file);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', opts.uploadUrl);
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    xhr.setRequestHeader('X-CSRFToken', csrftoken);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded); };
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300) ? resolve() : reject(new Error('HTTP ' + xhr.status));
    xhr.onerror = () => reject(new Error('network error'));
    xhr.send(fd);
  });
}

function chunkedUpload(file, opts, onProgress) {
  const chunkSize = window.SCLOUD_CHUNK_SIZE;
  const totalChunks = Math.ceil(file.size / chunkSize);
  const uploadId = (window.crypto && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`).replace(/[^a-zA-Z0-9]/g, '');

  function sendChunk(chunkIndex) {
    return new Promise((resolve, reject) => {
      const start = chunkIndex * chunkSize;
      const end = Math.min(start + chunkSize, file.size);
      const blob = file.slice(start, end);

      const fd = new FormData();
      if (opts.space) fd.append('space', opts.space);
      if (opts.groupId) fd.append('group_id', opts.groupId);
      if (opts.folderId) fd.append('folder_id', opts.folderId);
      fd.append('upload_id', uploadId);
      fd.append('filename', file.name);
      fd.append('content_type', file.type || '');
      fd.append('chunk_index', chunkIndex);
      fd.append('total_chunks', totalChunks);
      fd.append('chunk', blob, file.name);

      const xhr = new XMLHttpRequest();
      xhr.open('POST', opts.chunkUrl);
      xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
      xhr.setRequestHeader('X-CSRFToken', csrftoken);
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(start + e.loaded); };
      xhr.onload = () => (xhr.status >= 200 && xhr.status < 300) ? resolve() : reject(new Error('HTTP ' + xhr.status));
      xhr.onerror = () => reject(new Error('network error'));
      xhr.send(fd);
    });
  }

  return (async () => {
    for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
      let attempt = 0;
      // Retry a failed chunk a few times with backoff before giving up -
      // this is what makes big uploads resilient on flaky mobile networks.
      // eslint-disable-next-line no-constant-condition
      while (true) {
        try {
          await sendChunk(chunkIndex);
          break;
        } catch (e) {
          attempt += 1;
          if (attempt >= 4) throw e;
          await new Promise((r) => setTimeout(r, 1000 * attempt));
        }
      }
    }
  })();
}

// ---------------------------------------------------------------------
// Tags
// ---------------------------------------------------------------------

function tagToggleUrl(fileId) {
  if (window.SCLOUD_SHARE_TOKEN) {
    return `/s/${window.SCLOUD_SHARE_TOKEN}/file/${fileId}/tag/`;
  }
  return `/file/${fileId}/tag/`;
}

function toggleTag(fileId, tagId, btn) {
  fetch(tagToggleUrl(fileId), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-CSRFToken': csrftoken,
    },
    body: `tag_id=${encodeURIComponent(tagId)}`,
  })
    .then((r) => r.json())
    .then((data) => {
      if (btn) btn.classList.toggle('active', data.added);
      if (window.SCLOUD_FILES) {
        const f = window.SCLOUD_FILES.find((x) => x.id === fileId);
        if (f) {
          const idx = f.tag_ids.indexOf(tagId);
          if (data.added && idx === -1) f.tag_ids.push(tagId);
          if (!data.added && idx !== -1) f.tag_ids.splice(idx, 1);
        }
      }
    });
}

function createTag(space, groupId) {
  const name = prompt('New tag name:');
  if (!name) return;
  const formData = new URLSearchParams();
  formData.append('space', space);
  if (groupId) formData.append('group_id', groupId);
  formData.append('name', name);

  fetch('/tags/create/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-CSRFToken': csrftoken,
    },
    body: formData.toString(),
  }).then(() => window.location.reload());
}

function sharedCreateTag() {
  const name = prompt('New tag name:');
  if (!name) return;
  fetch(`/s/${window.SCLOUD_SHARE_TOKEN}/tags/create/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-CSRFToken': csrftoken,
    },
    body: `name=${encodeURIComponent(name)}`,
  }).then(() => window.location.reload());
}

function submitMove(formId) {
  const form = document.getElementById(formId);
  form.submit();
}

// ---------------------------------------------------------------------
// Thumbnail polling
// ---------------------------------------------------------------------

function pollPendingThumbnails() {
  document.querySelectorAll('[data-thumb-pending="1"]').forEach((el) => {
    const fileId = el.getAttribute('data-file-id');
    pollOneThumbnail(el, fileId, 0);
  });
}

function pollOneThumbnail(el, fileId, attempt) {
  if (attempt > 40) return; // ~60s max
  fetch(`/file/${fileId}/status/`)
    .then((r) => r.json())
    .then((data) => {
      if (data.status === 'ready' && data.thumbnail_url) {
        el.innerHTML = `<img class="${el.dataset.imgClass || ''}" src="${data.thumbnail_url}" alt="">`;
        el.removeAttribute('data-thumb-pending');
        if (window.SCLOUD_FILES) {
          const f = window.SCLOUD_FILES.find((x) => String(x.id) === String(fileId));
          if (f) { f.thumb = data.thumbnail_url; f.thumbnail_status = 'ready'; }
        }
      } else if (data.status === 'pending') {
        setTimeout(() => pollOneThumbnail(el, fileId, attempt + 1), 1500);
      } else {
        el.removeAttribute('data-thumb-pending');
      }
    })
    .catch(() => {});
}

document.addEventListener('DOMContentLoaded', pollPendingThumbnails);

// ---------------------------------------------------------------------
// Multi-select + bulk download
// ---------------------------------------------------------------------

let selectMode = false;
const selectedIds = new Set();

function toggleSelectMode() {
  selectMode = !selectMode;
  document.body.classList.toggle('select-mode', selectMode);
  const btn = document.getElementById('select-toggle-btn');
  if (btn) btn.textContent = selectMode ? 'Cancel' : 'Select';
  const bar = document.getElementById('select-bar');
  if (bar) bar.classList.toggle('open', selectMode);
  if (!selectMode) {
    selectedIds.clear();
    document.querySelectorAll('.select-check.checked').forEach((el) => el.classList.remove('checked'));
    updateSelectCount();
  }
}

function toggleSelect(fileId, el) {
  if (!selectMode) toggleSelectMode();
  if (selectedIds.has(fileId)) {
    selectedIds.delete(fileId);
    el.classList.remove('checked');
  } else {
    selectedIds.add(fileId);
    el.classList.add('checked');
  }
  updateSelectCount();
}

function updateSelectCount() {
  const el = document.getElementById('select-count');
  if (el) el.textContent = `${selectedIds.size} selected`;
}

function handleItemClick(e, index, fileId) {
  if (selectMode) {
    e.preventDefault();
    const el = e.currentTarget.querySelector('.select-check');
    toggleSelect(fileId, el);
    return;
  }
  openLightbox(index);
}

// Downloads each selected file. Where the browser supports the Web Share
// API with files (most modern mobile browsers), images/videos are handed
// to the OS share sheet so the person can pick "Save to Photos" directly -
// that's the only way a website can get files into the camera roll. PDFs
// and other non-media files can't go to Photos anyway, so they always just
// download normally. Falls back to plain sequential downloads everywhere
// else (desktop, or when the share sheet isn't available/is cancelled).
async function downloadSelected() {
  const files = (window.SCLOUD_FILES || []).filter((f) => selectedIds.has(f.id));
  if (!files.length) return;

  const mediaFiles = files.filter((f) => f.is_image || f.is_video);
  const otherFiles = files.filter((f) => !f.is_image && !f.is_video);

  let sharedMedia = false;
  if (mediaFiles.length && navigator.share && navigator.canShare) {
    try {
      const blobFiles = await Promise.all(mediaFiles.map(async (f) => {
        const resp = await fetch(f.url);
        const blob = await resp.blob();
        return new File([blob], f.filename, { type: blob.type });
      }));
      if (navigator.canShare({ files: blobFiles })) {
        await navigator.share({ files: blobFiles });
        sharedMedia = true;
      }
    } catch (e) {
      sharedMedia = false; // user cancelled or share failed - fall back below
    }
  }

  const toSequentialDownload = sharedMedia ? otherFiles : files;
  sequentialDownload(toSequentialDownload);
}

function sequentialDownload(files) {
  let i = 0;
  function next() {
    if (i >= files.length) return;
    const f = files[i]; i += 1;
    const a = document.createElement('a');
    a.href = f.url;
    a.download = f.filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(next, 400);
  }
  next();
}

// ---------------------------------------------------------------------
// Full-screen media viewer (lightbox)
// ---------------------------------------------------------------------

let lightboxIndex = -1;

function lightboxFiles() {
  return window.SCLOUD_FILES || [];
}

function openLightbox(index) {
  lightboxIndex = index;
  renderLightbox();
  document.getElementById('lightbox').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeLightbox() {
  document.getElementById('lightbox').classList.remove('open');
  document.getElementById('lightbox-menu').classList.remove('open');
  document.getElementById('lightbox-media').innerHTML = '';
  document.body.style.overflow = '';
}

function lightboxPrev() {
  if (lightboxIndex > 0) {
    lightboxIndex -= 1;
    renderLightbox();
  }
}

function lightboxNext() {
  const files = lightboxFiles();
  if (lightboxIndex < files.length - 1) {
    lightboxIndex += 1;
    renderLightbox();
  }
}

function renderLightbox() {
  const files = lightboxFiles();
  const file = files[lightboxIndex];
  if (!file) { closeLightbox(); return; }

  document.getElementById('lightbox-title').textContent = file.filename;
  const mediaEl = document.getElementById('lightbox-media');
  const shareSuffix = window.SCLOUD_SHARE_TOKEN ? `?share=${window.SCLOUD_SHARE_TOKEN}` : '';

  if (file.is_image) {
    mediaEl.innerHTML = `<img src="${file.url}${shareSuffix}" alt="${escapeHtml(file.filename)}">`;
  } else if (file.is_video) {
    mediaEl.innerHTML = `<video src="${file.url}${shareSuffix}" controls autoplay playsinline></video>`;
  } else {
    mediaEl.innerHTML = `<div class="generic-file"><div class="icon">📄</div><div>${escapeHtml(file.filename)}</div></div>`;
  }

  document.getElementById('lightbox-prev').disabled = lightboxIndex <= 0;
  document.getElementById('lightbox-next').disabled = lightboxIndex >= files.length - 1;

  const downloadLink = document.getElementById('lightbox-download-link');
  if (downloadLink) downloadLink.href = file.url + shareSuffix;

  document.getElementById('lightbox-menu').classList.remove('open');
  renderLightboxMenu();
}

function renderLightboxMenu() {
  const files = lightboxFiles();
  const file = files[lightboxIndex];
  if (!file) return;
  const tags = window.SCLOUD_TAGS || [];
  const readOnly = !!window.SCLOUD_READ_ONLY_LIGHTBOX;
  const canManageTags = !readOnly || window.SCLOUD_SHARE_CAN_MANAGE_TAGS;

  const tagChips = tags.map((t) => {
    const active = file.tag_ids.includes(t.id) ? 'active' : '';
    return `<span class="tag-chip ${active}" onclick="toggleTag(${file.id}, ${t.id}, this)">${escapeHtml(t.name)}</span>`;
  }).join('');

  const menuBody = document.getElementById('lightbox-menu-body');
  let html = `
    <h3>${escapeHtml(file.filename)}</h3>
    <p style="color:var(--text-secondary);font-size:13px;">${file.size_human} &middot; Uploaded ${file.uploaded_at}</p>
  `;

  if (canManageTags) {
    html += `
      <div class="form-group">
        <label>Tags</label>
        <div class="tag-chip-row">${tagChips || '<span style="color:var(--text-secondary);font-size:13px;">No tags yet</span>'}</div>
      </div>
    `;
  }

  const shareSuffix = window.SCLOUD_SHARE_TOKEN ? `?share=${window.SCLOUD_SHARE_TOKEN}` : '';
  html += `<a class="btn secondary block" href="${file.url}${shareSuffix}" download style="margin-bottom:8px;">Download</a>`;

  if (!readOnly) {
    html += `
      <button type="button" class="btn secondary block" style="margin-bottom:8px;" onclick="openLightboxMove()">Move</button>
      <button type="button" class="btn danger block" style="margin-bottom:8px;" onclick="lightboxDelete()">Delete</button>
    `;
  }

  html += `<button type="button" class="btn secondary block" onclick="document.getElementById('lightbox-menu').classList.remove('open')">Close menu</button>`;
  menuBody.innerHTML = html;
}

function toggleLightboxMenu() {
  document.getElementById('lightbox-menu').classList.toggle('open');
}

function openLightboxMove() {
  const folders = window.SCLOUD_FOLDERS || [];
  const options = ['<option value="">(Root)</option>']
    .concat(folders.map((f) => `<option value="${f.id}">${escapeHtml(f.name)}</option>`))
    .join('');

  const menuBody = document.getElementById('lightbox-menu-body');
  menuBody.innerHTML = `
    <h3>Move file</h3>
    <div class="form-group">
      <label>Destination folder</label>
      <select id="lightbox-move-dest">${options}</select>
    </div>
    <button type="button" class="btn block" style="margin-bottom:8px;" onclick="lightboxMoveConfirm()">Move</button>
    <button type="button" class="btn secondary block" onclick="renderLightboxMenu()">Cancel</button>
  `;
}

function lightboxMoveConfirm() {
  const files = lightboxFiles();
  const file = files[lightboxIndex];
  const dest = document.getElementById('lightbox-move-dest').value;

  fetch(`/file/${file.id}/move/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-CSRFToken': csrftoken,
      'X-Requested-With': 'XMLHttpRequest',
    },
    body: `dest_folder_id=${encodeURIComponent(dest)}`,
  }).then(() => window.location.reload());
}

function lightboxDelete() {
  const files = lightboxFiles();
  const file = files[lightboxIndex];
  if (!confirm(`Delete "${file.filename}"? This cannot be undone.`)) return;

  fetch(`/file/${file.id}/delete/`, {
    method: 'POST',
    headers: {
      'X-CSRFToken': csrftoken,
      'X-Requested-With': 'XMLHttpRequest',
    },
  })
    .then((r) => r.json())
    .then(() => {
      files.splice(lightboxIndex, 1);
      const gridEl = document.querySelector(`[data-grid-file-id="${file.id}"]`);
      if (gridEl) gridEl.remove();
      const rowEl = document.querySelector(`[data-row-file-id="${file.id}"]`);
      if (rowEl) rowEl.remove();

      if (!files.length) {
        closeLightbox();
        return;
      }
      if (lightboxIndex >= files.length) lightboxIndex = files.length - 1;
      renderLightbox();
    });
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

document.addEventListener('keydown', (e) => {
  const lb = document.getElementById('lightbox');
  if (!lb || !lb.classList.contains('open')) return;
  if (e.key === 'Escape') closeLightbox();
  if (e.key === 'ArrowLeft') lightboxPrev();
  if (e.key === 'ArrowRight') lightboxNext();
});
