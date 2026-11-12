/**
 * AgentRater · AI 智能体点评平台 — 详情页逻辑
 * 零外部依赖，中文界面
 */
(function () {
  'use strict';

  /* ========== 常量 & DOM ========== */
  var FAV_KEY = 'agentrater_favorites';
  var LIKE_KEY = 'agentrater_review_likes';
  var DATA_URL = 'data/agents.json';

  var detailMain = document.getElementById('detailMain');
  var favBtn = document.getElementById('favBtn');

  /* ========== URL 参数 ========== */
  function getAgentId() {
    var params = new URLSearchParams(window.location.search);
    return params.get('id');
  }

  /* ========== localStorage 工具 ========== */
  function getFavorites() {
    try { return JSON.parse(localStorage.getItem(FAV_KEY)) || []; }
    catch (e) { return []; }
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
  }

  function getLikedReviews() {
    try { return JSON.parse(localStorage.getItem(LIKE_KEY)) || {}; }
    catch (e) { return {}; }
  }
  function setLikedReviews(obj) {
    localStorage.setItem(LIKE_KEY, JSON.stringify(obj));
  }
  function isReviewLiked(agentId, reviewIdx) {
    var key = agentId + '_' + reviewIdx;
    return !!getLikedReviews()[key];
  }
  function toggleReviewLike(agentId, reviewIdx) {
    var liked = getLikedReviews();
    var key = agentId + '_' + reviewIdx;
    if (liked[key]) { delete liked[key]; } else { liked[key] = true; }
    setLikedReviews(liked);
    return !liked[key]; // returns false if now unliked (we deleted), true if now liked
    // Actually after delete, liked[key] is undefined, so we return whether it's NOW liked
  }

  /* ========== 星级渲染 ========== */
  function renderStars(rating, sizeClass) {
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

  /* ========== 评分分布计算 ========== */
  function computeRatingDist(rating, reviewCount) {
    // Simulate a realistic distribution centered around the overall rating
    // Use a Gaussian-like weighting for each star level
    var weights = [];
    var totalWeight = 0;
    for (var s = 1; s <= 5; s++) {
      // Gaussian centered at `rating`, sigma = 0.8
      var diff = s - rating;
      var w = Math.exp(-(diff * diff) / (2 * 0.64));
      weights.push(w);
      totalWeight += w;
    }
    var dist = {};
    var allocated = 0;
    for (var s2 = 1; s2 <= 5; s2++) {
      var count = Math.round((weights[s2 - 1] / totalWeight) * reviewCount);
      dist[s2] = count;
      allocated += count;
    }
    // Adjust the peak star to match exact total
    var peakStar = Math.round(rating);
    if (peakStar < 1) peakStar = 1;
    if (peakStar > 5) peakStar = 5;
    dist[peakStar] += (reviewCount - allocated);

    return dist;
  }

  /* ========== HTML 转义 ========== */
  function escHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  /* ========== 渲染详情页 ========== */
  function renderDetail(agent) {
    var faved = isFav(agent.id);
    var dist = computeRatingDist(agent.rating, agent.reviewCount);
    var maxDistCount = 0;
    for (var s = 1; s <= 5; s++) {
      if (dist[s] > maxDistCount) maxDistCount = dist[s];
    }

    // Tags HTML
    var tagsHtml = agent.tags.map(function (t) {
      return '<span class="tag-pill">' + escHtml(t) + '</span>';
    }).join('');

    // Rating distribution bars (5 → 1)
    var distRowsHtml = '';
    for (var star = 5; star >= 1; star--) {
      var count = dist[star] || 0;
      var pct = maxDistCount > 0 ? (count / maxDistCount * 100) : 0;
      distRowsHtml +=
        '<div class="dist-row">' +
          '<span class="dist-label">' + star + '星</span>' +
          '<div class="dist-bar-track"><div class="dist-bar-fill" style="width:' + pct.toFixed(1) + '%"></div></div>' +
          '<span class="dist-count">' + count + '</span>' +
        '</div>';
    }

    // Reviews HTML
    var reviewsHtml = '';
    agent.reviews.forEach(function (rev, idx) {
      var liked = isReviewLiked(agent.id, idx);
      reviewsHtml +=
        '<div class="review-item" data-review-idx="' + idx + '">' +
          '<div class="review-top">' +
            '<span class="review-user">' + escHtml(rev.username) + '</span>' +
            '<span class="review-stars">' + renderStars(rev.rating) + '</span>' +
          '</div>' +
          '<p class="review-content">' + escHtml(rev.content) + '</p>' +
          '<div class="review-actions">' +
            '<button class="like-btn' + (liked ? ' liked' : '') + '" data-like-idx="' + idx + '" aria-label="点赞">' +
              '<span class="like-icon">' + (liked ? '👍' : '👏') + '</span>' +
              '<span class="like-text">' + (liked ? '已赞' : '点赞') + '</span>' +
            '</button>' +
          '</div>' +
        '</div>';
    });

    var html =
      /* 顶部信息区 */
      '<div class="detail-header">' +
        '<div class="detail-img-wrap">' +
          '<img src="' + escHtml(agent.image) + '" alt="' + escHtml(agent.name) + '">' +
        '</div>' +
        '<div class="detail-info">' +
          '<h1 class="detail-name">' + escHtml(agent.name) + '</h1>' +
          '<span class="detail-category">' + escHtml(agent.category) + '</span>' +
          '<div class="detail-rating-row">' +
            '<span class="stars" aria-label="评分' + agent.rating + '星">' + renderStars(agent.rating) + '</span>' +
            '<span class="rating-num">' + agent.rating.toFixed(1) + '</span>' +
            '<span class="review-count">(' + agent.reviewCount + '条评价)</span>' +
          '</div>' +
          '<div class="detail-tags">' + tagsHtml + '</div>' +
          '<p class="detail-summary">' + escHtml(agent.summary) + '</p>' +
          '<button class="detail-fav-btn' + (faved ? ' faved' : '') + '" id="detailFavBtn" aria-label="' + (faved ? '取消收藏' : '收藏') + '">' +
            '<span class="fav-heart">' + (faved ? '❤️' : '🤍') + '</span>' +
            '<span class="fav-text">' + (faved ? '已收藏' : '收藏') + '</span>' +
          '</button>' +
        '</div>' +
      '</div>' +

      /* 评分分布 + 评价列表 */
      '<div class="detail-body">' +
        /* 评分分布 */
        '<div class="rating-dist-card">' +
          '<h2 class="rating-dist-title">评分分布</h2>' +
          distRowsHtml +
          '<div class="dist-avg-row">' +
            '<span class="dist-avg-num">' + agent.rating.toFixed(1) + '</span>' +
            '<span class="dist-avg-label">平均评分</span>' +
          '</div>' +
        '</div>' +

        /* 评价列表 */
        '<div class="reviews-card">' +
          '<h2 class="reviews-title">用户评价 (' + agent.reviews.length + ')</h2>' +
          reviewsHtml +
        '</div>' +
      '</div>';

    detailMain.innerHTML = html;

    // Update page title
    document.title = agent.name + ' · AgentRater';

    // Bind events after render
    bindDetailEvents(agent);
  }

  /* ========== 渲染 404 ========== */
  function renderNotFound() {
    detailMain.innerHTML =
      '<div class="detail-not-found">' +
        '<span class="nf-icon">🤖</span>' +
        '<p>未找到该 Agent，可能已被下架或链接有误</p>' +
        '<a href="index.html"><span>←</span> 返回列表</a>' +
      '</div>';
    document.title = '未找到 · AgentRater';
  }

  /* ========== 事件绑定 ========== */
  function bindDetailEvents(agent) {
    // 收藏按钮（详情页大按钮）
    var detailFavBtn = document.getElementById('detailFavBtn');
    if (detailFavBtn) {
      detailFavBtn.addEventListener('click', function () {
        toggleFav(agent.id);
        var nowFav = isFav(agent.id);
        detailFavBtn.classList.toggle('faved', nowFav);
        detailFavBtn.querySelector('.fav-heart').textContent = nowFav ? '❤️' : '🤍';
        detailFavBtn.querySelector('.fav-text').textContent = nowFav ? '已收藏' : '收藏';
        detailFavBtn.setAttribute('aria-label', nowFav ? '取消收藏' : '收藏');
        // 同步导航栏收藏按钮状态
        updateNavFavBtn(agent.id);
      });
    }

    // 导航栏收藏按钮
    if (favBtn) {
      updateNavFavBtn(agent.id);
      favBtn.addEventListener('click', function () {
        toggleFav(agent.id);
        updateNavFavBtn(agent.id);
        // 同步详情页收藏按钮
        if (detailFavBtn) {
          var nowFav = isFav(agent.id);
          detailFavBtn.classList.toggle('faved', nowFav);
          detailFavBtn.querySelector('.fav-heart').textContent = nowFav ? '❤️' : '🤍';
          detailFavBtn.querySelector('.fav-text').textContent = nowFav ? '已收藏' : '收藏';
          detailFavBtn.setAttribute('aria-label', nowFav ? '取消收藏' : '收藏');
        }
      });
    }

    // 评价点赞按钮（事件委托）
    var reviewsCard = detailMain.querySelector('.reviews-card');
    if (reviewsCard) {
      reviewsCard.addEventListener('click', function (e) {
        var likeBtn = e.target.closest('.like-btn');
        if (!likeBtn) return;
        var idx = parseInt(likeBtn.getAttribute('data-like-idx'), 10);
        var key = agent.id + '_' + idx;
        var likedMap = getLikedReviews();
        var wasLiked = !!likedMap[key];
        if (wasLiked) {
          delete likedMap[key];
        } else {
          likedMap[key] = true;
        }
        setLikedReviews(likedMap);
        var nowLiked = !wasLiked;
        likeBtn.classList.toggle('liked', nowLiked);
        likeBtn.querySelector('.like-icon').textContent = nowLiked ? '👍' : '👏';
        likeBtn.querySelector('.like-text').textContent = nowLiked ? '已赞' : '点赞';
      });
    }
  }

  function updateNavFavBtn(agentId) {
    if (!favBtn) return;
    var nowFav = isFav(agentId);
    favBtn.classList.toggle('active', nowFav);
  }

  /* ========== 初始化 ========== */
  function init() {
    var agentId = getAgentId();
    if (!agentId) {
      renderNotFound();
      return;
    }

    fetch(DATA_URL)
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        // Find agent by id
        var agent = null;
        for (var i = 0; i < data.length; i++) {
          if (data[i].id === agentId) {
            agent = data[i];
            break;
          }
        }
        if (!agent) {
          renderNotFound();
          return;
        }
        renderDetail(agent);
      })
      .catch(function (err) {
        console.error('加载 Agent 数据失败:', err);
        renderNotFound();
      });
  }

  init();
})();
