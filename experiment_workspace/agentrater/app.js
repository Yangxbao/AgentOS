/**
 * AgentRater · AI 智能体点评平台 — 首页逻辑
 * 零外部依赖，中文界面
 */
(function () {
  'use strict';

  /* ========== 常量 & DOM ========== */
  var FAV_KEY = 'agentrater_favorites';
  var DATA_URL = 'data/agents.json';

  var cardGrid    = document.getElementById('cardGrid');
  var emptyState  = document.getElementById('emptyState');
  var searchInput = document.getElementById('searchInput');
  var searchClear = document.getElementById('searchClear');
  var categoryTabs = document.getElementById('categoryTabs');
  var sortGroup   = document.getElementById('sortGroup');
  var favFilterBtn = document.getElementById('favFilterBtn');
  var favBadge    = document.getElementById('favBadge');

  /* ========== 状态 ========== */
  var agents = [];
  var currentCategory = '全部';
  var currentSort = 'default';
  var currentKeyword = '';
  var favOnly = false;
  var debounceTimer = null;

  /* ========== localStorage 工具 ========== */
  function getFavorites() {
    try {
      return JSON.parse(localStorage.getItem(FAV_KEY)) || [];
    } catch (e) { return []; }
  }
  function setFavorites(arr) {
    localStorage.setItem(FAV_KEY, JSON.stringify(arr));
  }
  function isFav(id) {
    return getFavorites().indexOf(id) !== -1;
  }
  function toggleFav(id) {
    var favs = getFavorites();
    var idx = favs.indexOf(id);
    if (idx === -1) { favs.push(id); } else { favs.splice(idx, 1); }
    setFavorites(favs);
    updateFavBadge();
    renderCards();
  }
  function updateFavBadge() {
    var count = getFavorites().length;
    favBadge.textContent = count;
    favBadge.setAttribute('data-count', count);
  }

  /* ========== 星级渲染 ========== */
  function renderStars(rating) {
    var html = '';
    var full = Math.floor(rating);
    var hasHalf = (rating - full) >= 0.3 && (rating - full) < 0.8;
    if ((rating - full) >= 0.8) { full += 1; hasHalf = false; }
    var empty = 5 - full - (hasHalf ? 1 : 0);
    for (var i = 0; i < full; i++) {
      html += '<span class="star-filled" aria-hidden="true">★</span>';
    }
    if (hasHalf) {
      html += '<span class="star-half" aria-hidden="true">★</span>';
    }
    for (var j = 0; j < empty; j++) {
      html += '<span class="star-empty" aria-hidden="true">★</span>';
    }
    return html;
  }

  /* ========== 卡片渲染 ========== */
  function createCard(agent) {
    var faved = isFav(agent.id);
    var card = document.createElement('article');
    card.className = 'agent-card';
    card.setAttribute('data-id', agent.id);

    var tagsHtml = agent.tags.map(function (t) {
      return '<span class="tag-pill">' + escHtml(t) + '</span>';
    }).join('');

    card.innerHTML =
      '<div class="card-img-wrap">' +
        '<img src="' + escHtml(agent.image) + '" alt="' + escHtml(agent.name) + '" loading="lazy">' +
        '<button class="card-fav' + (faved ? ' faved' : '') + '" aria-label="' + (faved ? '取消收藏' : '收藏') + '" data-fav-id="' + escHtml(agent.id) + '">' +
          (faved ? '❤️' : '🤍') +
        '</button>' +
      '</div>' +
      '<div class="card-body">' +
        '<h3 class="card-name">' + escHtml(agent.name) + '</h3>' +
        '<span class="card-category">' + escHtml(agent.category) + '</span>' +
        '<div class="card-rating">' +
          '<span class="stars" aria-label="评分' + agent.rating + '星">' + renderStars(agent.rating) + '</span>' +
          '<span class="rating-num">' + agent.rating.toFixed(1) + '</span>' +
          '<span class="review-count">(' + agent.reviewCount + '条评价)</span>' +
        '</div>' +
        '<p class="card-summary">' + escHtml(agent.summary) + '</p>' +
        '<div class="card-tags">' + tagsHtml + '</div>' +
      '</div>';

    return card;
  }

  function escHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  /* ========== 过滤 & 排序 ========== */
  function getFilteredAgents() {
    var list = agents.slice();

    // 关键词搜索
    if (currentKeyword) {
      var kw = currentKeyword.toLowerCase();
      list = list.filter(function (a) {
        return a.name.toLowerCase().indexOf(kw) !== -1 ||
               a.summary.toLowerCase().indexOf(kw) !== -1 ||
               a.tags.some(function (t) { return t.toLowerCase().indexOf(kw) !== -1; });
      });
    }

    // 分类筛选
    if (currentCategory !== '全部') {
      list = list.filter(function (a) { return a.category === currentCategory; });
    }

    // 仅看收藏
    if (favOnly) {
      var favs = getFavorites();
      list = list.filter(function (a) { return favs.indexOf(a.id) !== -1; });
    }

    // 排序
    if (currentSort === 'rating') {
      list.sort(function (a, b) { return b.rating - a.rating; });
    } else if (currentSort === 'reviewCount') {
      list.sort(function (a, b) { return b.reviewCount - a.reviewCount; });
    } else {
      list.sort(function (a, b) { return a.id.localeCompare(b.id); });
    }

    return list;
  }

  /* ========== 渲染入口 ========== */
  function renderCards() {
    var filtered = getFilteredAgents();
    cardGrid.innerHTML = '';

    if (filtered.length === 0) {
      emptyState.style.display = '';
      return;
    }
    emptyState.style.display = 'none';

    var fragment = document.createDocumentFragment();
    filtered.forEach(function (agent) {
      fragment.appendChild(createCard(agent));
    });
    cardGrid.appendChild(fragment);
  }

  /* ========== 事件绑定 ========== */

  // 搜索（防抖 300ms）
  searchInput.addEventListener('input', function () {
    clearTimeout(debounceTimer);
    var val = searchInput.value.trim();
    searchClear.style.display = val ? '' : 'none';
    debounceTimer = setTimeout(function () {
      currentKeyword = val;
      renderCards();
    }, 300);
  });

  // 清空搜索
  searchClear.addEventListener('click', function () {
    searchInput.value = '';
    currentKeyword = '';
    searchClear.style.display = 'none';
    renderCards();
    searchInput.focus();
  });

  // 分类 Tab
  categoryTabs.addEventListener('click', function (e) {
    var tab = e.target.closest('.cat-tab');
    if (!tab) return;
    var tabs = categoryTabs.querySelectorAll('.cat-tab');
    tabs.forEach(function (t) { t.classList.remove('active'); });
    tab.classList.add('active');
    currentCategory = tab.getAttribute('data-category');
    renderCards();
  });

  // 排序
  sortGroup.addEventListener('click', function (e) {
    var btn = e.target.closest('.sort-btn');
    if (!btn) return;
    var btns = sortGroup.querySelectorAll('.sort-btn');
    btns.forEach(function (b) { b.classList.remove('active'); });
    btn.classList.add('active');
    currentSort = btn.getAttribute('data-sort');
    renderCards();
  });

  // 仅看收藏
  favFilterBtn.addEventListener('click', function () {
    favOnly = !favOnly;
    favFilterBtn.classList.toggle('active', favOnly);
    renderCards();
  });

  // 卡片点击（事件委托）
  cardGrid.addEventListener('click', function (e) {
    // 收藏按钮
    var favBtn = e.target.closest('.card-fav');
    if (favBtn) {
      e.stopPropagation();
      var id = favBtn.getAttribute('data-fav-id');
      toggleFav(id);
      return;
    }
    // 卡片跳转详情
    var card = e.target.closest('.agent-card');
    if (card) {
      var id = card.getAttribute('data-id');
      window.location.href = 'agent.html?id=' + encodeURIComponent(id);
    }
  });

  /* ========== 初始化 ========== */
  function init() {
    updateFavBadge();

    fetch(DATA_URL)
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        agents = data;
        renderCards();
      })
      .catch(function (err) {
        console.error('加载 Agent 数据失败:', err);
        emptyState.style.display = '';
        emptyState.querySelector('p').textContent = '数据加载失败，请刷新页面重试';
      });
  }

  init();
})();
