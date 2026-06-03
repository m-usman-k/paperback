/* main.js - Paper Library frontend */

(function () {
  'use strict';

  // State
  let papers = [];
  let tags = [];
  let activeTagId = null;
  let tagPendingPaperId = null;
  let searchQuery = '';

  const TAG_COLOURS = [
    '#FDA4AF', '#FCD34D', '#FDE68A',
    '#86EFAC', '#93C5FD', '#C4B5FD',
  ];
  let selectedColour = TAG_COLOURS[4]; // blue default

  // DOM refs
  const searchInput    = document.getElementById('search-input');
  const paperList      = document.getElementById('paper-list');
  const emptyState     = document.getElementById('empty-state');
  const dropZone       = document.getElementById('drop-zone');
  const uploadProgress = document.getElementById('upload-progress');
  const sidebarTags    = document.getElementById('sidebar-tags');
  const tagNameInput   = document.getElementById('tag-name-input');
  const colourRow      = document.getElementById('colour-row');
  const btnAddTag      = document.getElementById('btn-add-tag');
  const btnHf          = document.getElementById('btn-hf');
  const bulkActions       = document.getElementById('bulk-actions');
  const cbSelectAll       = document.getElementById('cb-select-all');
  const bulkSelectedCount = document.getElementById('bulk-selected-count');
  const btnBulkDelete     = document.getElementById('btn-bulk-delete');

  // API helpers
  async function api(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    if (res.status === 204) return null;
    return res.json();
  }

  // Toast
  function toast(msg, type = '') {
    const el = document.createElement('div');
    el.className = 'toast' + (type ? ' ' + type : '');
    el.textContent = msg;
    document.getElementById('toast-container').appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  // Render sidebar tags
  function renderSidebar() {
    sidebarTags.innerHTML = '';

    // "All" entry
    const all = document.createElement('div');
    all.className = 'tag-item' + (activeTagId === null ? ' active' : '');
    all.innerHTML = `<span class="tag-dot" style="background:#CBD5E1"></span><span class="tag-label">All papers</span>`;
    all.addEventListener('click', () => { activeTagId = null; loadPapers(); });
    sidebarTags.appendChild(all);

    tags.forEach(tag => {
      const item = document.createElement('div');
      item.className = 'tag-item' + (activeTagId === tag.id ? ' active' : '');
      item.dataset.tagId = tag.id;
      item.innerHTML = `
        <span class="tag-dot" style="background:${tag.colour}"></span>
        <span class="tag-label">${esc(tag.name)}</span>
        <button class="tag-del" title="Delete tag" data-tid="${tag.id}">×</button>`;
      item.addEventListener('click', (e) => {
        if (e.target.closest('.tag-del')) return;
        activeTagId = tag.id;
        loadPapers();
      });
      item.querySelector('.tag-del').addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!await customConfirm(`Delete tag "${tag.name}"?`)) return;
        await api('DELETE', `/api/tags/${tag.id}`);
        if (activeTagId === tag.id) activeTagId = null;
        await loadTags();
        await loadPapers();
      });
      sidebarTags.appendChild(item);
    });
  }

  // Colour swatches
  function renderColourRow() {
    colourRow.innerHTML = '';
    TAG_COLOURS.forEach(c => {
      const sw = document.createElement('div');
      sw.className = 'colour-swatch' + (c === selectedColour ? ' selected' : '');
      sw.style.background = c;
      sw.addEventListener('click', () => {
        selectedColour = c;
        renderColourRow();
      });
      colourRow.appendChild(sw);
    });
  }

  // Render paper list
  function renderPapers() {
    paperList.innerHTML = '';
    const visible = filterPapers();

    if (visible.length === 0) {
      emptyState.style.display = '';
      updateBulkActionsUI();
      return;
    }
    emptyState.style.display = 'none';

    visible.forEach(paper => {
      const authors = Array.isArray(paper.authors)
        ? paper.authors.slice(0, 4).join(', ') + (paper.authors.length > 4 ? ' et al.' : '')
        : paper.authors;

      const tagChips = paper.tags.map(t => `
        <span class="tag-chip" style="background:${t.colour}20; color:${darken(t.colour)}"
              data-paper-id="${paper.id}" data-tag-id="${t.id}">
          ${esc(t.name)}
          <span class="chip-del" title="Remove tag">×</span>
        </span>`).join('');

      const row = document.createElement('div');
      row.className = 'paper-row';
      row.dataset.paperId = paper.id;
      row.innerHTML = `
        <input type="checkbox" class="paper-checkbox" aria-label="Select paper" data-paper-id="${paper.id}">
        <div class="paper-body">
          <div class="paper-title" tabindex="0" role="button"
               aria-label="Open ${esc(paper.title)}"
               data-paper-id="${paper.id}">${esc(paper.title)}</div>
          <div class="paper-authors">${esc(authors)}</div>
          <div class="paper-meta">
            <span class="meta-badge">${esc(paper.category || 'arXiv')}</span>
            ${paper.year ? `<span class="meta-badge">${paper.year}</span>` : ''}
            <span class="meta-badge">${esc(paper.source || 'Preprint')}</span>
          </div>
        </div>
        <div class="paper-actions">
          <button class="btn-pdf" data-paper-id="${paper.id}">PDF</button>
          <div class="paper-tag-chips">${tagChips}</div>
          <button class="btn-tag-paper" data-paper-id="${paper.id}">+ Tag</button>
        </div>`;

      // title click → viewer
      row.querySelector('.paper-title').addEventListener('click', () => {
        window.location.href = `/viewer/${paper.id}`;
      });
      row.querySelector('.paper-title').addEventListener('keydown', e => {
        if (e.key === 'Enter') window.location.href = `/viewer/${paper.id}`;
      });

      // pdf button
      row.querySelector('.btn-pdf').addEventListener('click', () => {
        window.location.href = `/viewer/${paper.id}`;
      });

      // tag assign
      row.querySelector('.btn-tag-paper').addEventListener('click', () => {
        openTagModal(paper.id);
      });

      // remove tag chip
      row.querySelectorAll('.chip-del').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const chip = btn.closest('.tag-chip');
          const pid = chip.dataset.paperId;
          const tid = chip.dataset.tagId;
          await api('DELETE', `/api/papers/${pid}/tags/${tid}`);
          await loadPapers();
        });
      });

      paperList.appendChild(row);
    });
    
    updateBulkActionsUI();
  }
  
  function updateBulkActionsUI() {
    const visible = filterPapers();
    if (visible.length === 0) {
      bulkActions.style.display = 'none';
      return;
    }
    
    bulkActions.style.display = 'flex';
    const checkboxes = Array.from(document.querySelectorAll('.paper-checkbox'));
    const checked = checkboxes.filter(cb => cb.checked);
    
    cbSelectAll.checked = checkboxes.length > 0 && checked.length === checkboxes.length;
    cbSelectAll.indeterminate = checked.length > 0 && checked.length < checkboxes.length;
    
    bulkSelectedCount.textContent = `${checked.length} selected`;
    btnBulkDelete.style.display = checked.length > 0 ? '' : 'none';
  }

  function filterPapers() {
    // Text search (including body_text) is handled server-side via loadPapers().
    // Only tag filtering is applied here as a lightweight client pass.
    let list = papers;
    if (activeTagId !== null) {
      list = list.filter(p => p.tags.some(t => t.id === activeTagId));
    }
    return list;
  }

  // Tag assignment modal
  function openTagModal(paperId) {
    tagPendingPaperId = paperId;
    const paper = papers.find(p => p.id === paperId);
    const assignedIds = new Set(paper.tags.map(t => t.id));

    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.id = 'tag-modal';
    backdrop.innerHTML = `
      <div class="modal" role="dialog" aria-label="Assign tags">
        <h3>Assign Tags</h3>
        <div id="tag-assign-list"></div>
        <div class="modal-footer">
          <button class="btn-cancel" id="btn-close-tag-modal">Close</button>
        </div>
      </div>`;

    const list = backdrop.querySelector('#tag-assign-list');
    tags.forEach(tag => {
      const item = document.createElement('div');
      item.className = 'tag-assign-item' + (assignedIds.has(tag.id) ? ' assigned' : '');
      item.style.background = assignedIds.has(tag.id) ? tag.colour + '30' : '';
      item.style.borderColor = assignedIds.has(tag.id) ? tag.colour : '';
      item.innerHTML = `<span class="tag-dot" style="background:${tag.colour}"></span>${esc(tag.name)}`;
      item.addEventListener('click', async () => {
        if (assignedIds.has(tag.id)) {
          await api('DELETE', `/api/papers/${paperId}/tags/${tag.id}`);
          assignedIds.delete(tag.id);
          item.classList.remove('assigned');
          item.style.background = '';
          item.style.borderColor = '';
        } else {
          await api('POST', `/api/papers/${paperId}/tags`, { tag_id: tag.id });
          assignedIds.add(tag.id);
          item.classList.add('assigned');
          item.style.background = tag.colour + '30';
          item.style.borderColor = tag.colour;
        }
        await loadPapers();
      });
      list.appendChild(item);
    });

    backdrop.querySelector('#btn-close-tag-modal').addEventListener('click', () => {
      backdrop.remove();
    });
    backdrop.addEventListener('click', e => { if (e.target === backdrop) backdrop.remove(); });
    document.body.appendChild(backdrop);
  }

  // Hugging Face modal
  function openHfModal() {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.id = 'hf-modal';
    backdrop.innerHTML = `
      <div class="modal" role="dialog" aria-label="Search Hugging Face papers">
        <h3>Search Hugging Face Papers</h3>
        <input type="search" id="hf-search-input" placeholder="e.g. attention is all you need" autocomplete="off">
        <button class="btn-primary" id="btn-hf-search">Search</button>
        <div id="hf-results" style="margin-top:12px"></div>
        <div class="modal-footer">
          <button class="btn-cancel" id="btn-close-hf-modal">Close</button>
        </div>
      </div>`;

    const input   = backdrop.querySelector('#hf-search-input');
    const results = backdrop.querySelector('#hf-results');
    const btnSearch = backdrop.querySelector('#btn-hf-search');

    async function doSearch() {
      const q = input.value.trim();
      if (!q) return;
      btnSearch.disabled = true;
      btnSearch.textContent = 'Searching…';
      input.disabled = true;
      results.innerHTML = '<div class="spinner-loader"></div>';
      try {
        const data = await api('GET', `/api/hf/search?q=${encodeURIComponent(q)}`);
        if (!Array.isArray(data)) {
          results.innerHTML = '<p style="color:#DC2626;font-size:13px;text-align:center">Search failed.</p>';
          return;
        }
        if (data.length === 0) {
          results.innerHTML = '<p style="color:var(--muted);font-size:13px;text-align:center">No results.</p>';
          return;
        }
        results.innerHTML = '';
        data.forEach(item => {
          const authorStr = Array.isArray(item.authors) ? item.authors.slice(0, 3).join(', ') : '';
          const isExisting = item.in_library;
          
          const btnHtml = isExisting
            ? `<button class="btn-import" disabled style="background: #64748b; border-color: #64748b; color: white;">Already in library</button>`
            : `<button class="btn-import" data-arxiv-id="${esc(item.arxiv_id)}">Import</button>`;

          const el = document.createElement('div');
          el.className = 'hf-item';
          el.innerHTML = `
            <div>
              <div class="hf-item-title">${esc(item.title)}</div>
              <div class="hf-item-authors">${esc(authorStr)}</div>
            </div>
            ${btnHtml}`;
          if (!isExisting) {
            el.querySelector('.btn-import').addEventListener('click', async (e) => {
              const btn = e.currentTarget;
              btn.disabled = true;
              btn.textContent = 'Importing…';
              btn.style.width = 'auto';

              let timeElapsed = 0;
              const interval = setInterval(() => {
                timeElapsed += 1;
                if (timeElapsed >= 3 && timeElapsed < 12) {
                  btn.textContent = 'Querying arXiv…';
                } else if (timeElapsed >= 12 && timeElapsed < 22) {
                  btn.textContent = 'Retrying arXiv…';
                } else if (timeElapsed >= 22) {
                  btn.textContent = 'Downloading PDF…';
                }
              }, 1000);

              try {
                const res = await api('POST', '/api/hf/import', {
                  arxiv_id: item.arxiv_id,
                  title: item.title,
                  authors: item.authors,
                  year: item.year || null,
                });
                if (res && res.paper) {
                  toast(res.duplicate ? 'Already in library' : 'Paper imported', res.duplicate ? '' : 'success');
                  btn.textContent = res.duplicate ? 'Already in library' : 'Imported';
                  btn.style.background = '#64748b';
                  btn.style.borderColor = '#64748b';
                  await loadPapers();
                } else {
                  toast('Import failed', 'error');
                  btn.textContent = 'Retry Import';
                  btn.disabled = false;
                }
              } catch {
                toast('Import failed', 'error');
                btn.textContent = 'Retry Import';
                btn.disabled = false;
              } finally {
                clearInterval(interval);
              }
            });
          }
          results.appendChild(el);
        });
      } catch (err) {
        results.innerHTML = '<p style="color:#DC2626;font-size:13px;text-align:center">Search failed.</p>';
      } finally {
        btnSearch.disabled = false;
        btnSearch.textContent = 'Search';
        input.disabled = false;
      }
    }

    btnSearch.addEventListener('click', doSearch);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });

    backdrop.querySelector('#btn-close-hf-modal').addEventListener('click', () => backdrop.remove());
    backdrop.addEventListener('click', e => { if (e.target === backdrop) backdrop.remove(); });
    document.body.appendChild(backdrop);
    input.focus();
  }

  // Drag & drop upload
  function initDropZone() {
    // Spec: "Drop any PDF anywhere on the page"
    document.addEventListener('dragover', e => {
      if (e.dataTransfer && [...e.dataTransfer.types].includes('Files')) {
        e.preventDefault();
        dropZone.classList.add('over');
      }
    });

    document.addEventListener('dragleave', e => {
      // relatedTarget is null when the cursor leaves the browser window entirely
      if (!e.relatedTarget) dropZone.classList.remove('over');
    });

    document.addEventListener('drop', async e => {
      e.preventDefault();
      dropZone.classList.remove('over');
      const files = [...(e.dataTransfer.files || [])].filter(f => f.type === 'application/pdf');
      if (files.length === 0) { toast('Drop a PDF file', 'error'); return; }
      for (const file of files) await uploadFile(file);
    });

    // Click the drop zone to browse files
    dropZone.addEventListener('click', () => {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'application/pdf';
      input.multiple = true;
      input.onchange = async () => {
        for (const file of [...input.files]) await uploadFile(file);
      };
      input.click();
    });
  }

  async function uploadFile(file) {
    uploadProgress.style.display = '';
    const label = uploadProgress.querySelector('.label');
    label.textContent = `Uploading ${file.name}…`;

    let timeElapsed = 0;
    const interval = setInterval(() => {
      timeElapsed += 1;
      if (timeElapsed >= 3 && timeElapsed < 12) {
        label.textContent = `Processing ${file.name}: Querying arXiv for metadata…`;
      } else if (timeElapsed >= 12 && timeElapsed < 22) {
        label.textContent = `Processing ${file.name}: arXiv is slow, retrying query…`;
      } else if (timeElapsed >= 22) {
        label.textContent = `Processing ${file.name}: arXiv timed out, falling back to Hugging Face…`;
      }
    }, 1000);

    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await fetch('/api/papers/upload', { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) {
        toast(data.error || 'Upload failed', 'error');
      } else if (data.duplicate) {
        toast('Already in your library');
      } else {
        toast('Paper added', 'success');
        await loadPapers();
      }
    } catch {
      toast('Upload failed', 'error');
    } finally {
      clearInterval(interval);
      uploadProgress.style.display = 'none';
    }
  }

  // Data loading
  async function loadTags() {
    tags = await api('GET', '/api/tags');
    renderSidebar();
  }

  async function loadPapers() {
    const params = new URLSearchParams();
    if (activeTagId !== null) params.set('tag_id', activeTagId);
    if (searchQuery) params.set('q', searchQuery);
    papers = await api('GET', '/api/papers?' + params.toString());
    renderPapers();
    renderSidebar();
  }

  // Add tag
  btnAddTag.addEventListener('click', async () => {
    const name = tagNameInput.value.trim();
    if (!name) { tagNameInput.focus(); return; }
    const res = await api('POST', '/api/tags', { name, colour: selectedColour });
    if (res && res.id) {
      tagNameInput.value = '';
      toast('Tag created', 'success');
      await loadTags();
    } else {
      toast((res && res.error) || 'Could not create tag', 'error');
    }
  });

  tagNameInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') btnAddTag.click();
  });

  // Search
  let _searchTimer = null;
  searchInput.addEventListener('input', () => {
    searchQuery = searchInput.value.trim();
    clearTimeout(_searchTimer);
    // Debounce the server call (includes body_text search); 300 ms feels instant.
    _searchTimer = setTimeout(loadPapers, 300);
  });

  document.addEventListener('keydown', e => {
    if (e.key === '/' && document.activeElement !== searchInput) {
      e.preventDefault();
      searchInput.focus();
      searchInput.select();
    }
    if (e.key === 'Escape') {
      const modal = document.querySelector('.modal-backdrop');
      if (modal) modal.remove();
    }
  });

  // HF button
  btnHf.addEventListener('click', openHfModal);

  // Bulk Actions Event Listeners
  
  paperList.addEventListener('change', (e) => {
    if (e.target.classList.contains('paper-checkbox')) {
      updateBulkActionsUI();
    }
  });

  cbSelectAll.addEventListener('change', (e) => {
    const isChecked = e.target.checked;
    document.querySelectorAll('.paper-checkbox').forEach(cb => {
      cb.checked = isChecked;
    });
    updateBulkActionsUI();
  });

  btnBulkDelete.addEventListener('click', async () => {
    const checkedIds = Array.from(document.querySelectorAll('.paper-checkbox'))
      .filter(cb => cb.checked)
      .map(cb => parseInt(cb.dataset.paperId));
      
    if (checkedIds.length === 0) return;
    
    if (!await customConfirm(`Delete ${checkedIds.length} selected paper(s)?`)) return;
    
    await api('DELETE', '/api/papers/batch', { ids: checkedIds });
    toast(`Deleted ${checkedIds.length} paper(s)`);
    cbSelectAll.checked = false;
    cbSelectAll.indeterminate = false;
    await loadPapers();
  });

  // Utilities
  function customConfirm(message) {
    return new Promise(resolve => {
      const backdrop = document.createElement('div');
      backdrop.className = 'modal-backdrop';
      backdrop.style.zIndex = '9999';
      backdrop.innerHTML = `
        <div class="modal" role="dialog" style="max-width: 400px; text-align: center;">
          <h3 style="margin-top: 0; font-size: 16px;">Confirm</h3>
          <p style="margin-bottom: 24px; color: var(--muted);">${esc(message)}</p>
          <div style="display: flex; gap: 12px; justify-content: center;">
            <button class="btn-cancel" id="btn-confirm-no">Cancel</button>
            <button class="btn-primary" id="btn-confirm-yes" style="background: #DC2626; border-color: #DC2626;">Yes, proceed</button>
          </div>
        </div>
      `;
      document.body.appendChild(backdrop);

      backdrop.querySelector('#btn-confirm-yes').onclick = () => {
        backdrop.remove();
        resolve(true);
      };
      backdrop.querySelector('#btn-confirm-no').onclick = () => {
        backdrop.remove();
        resolve(false);
      };
    });
  }

  function esc(str) {
    return String(str ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function darken(hex) {
    // Return a darker version of a hex colour for chip text
    const n = parseInt(hex.slice(1), 16);
    const r = Math.max(0, (n >> 16) - 60);
    const g = Math.max(0, ((n >> 8) & 0xff) - 60);
    const b = Math.max(0, (n & 0xff) - 60);
    return `rgb(${r},${g},${b})`;
  }

  // Boot
  async function init() {
    renderColourRow();
    await loadTags();
    await loadPapers();
    initDropZone();
  }

  init();
})();
