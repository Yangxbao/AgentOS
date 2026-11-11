/**
 * 星舟科技官网 — 全站共享脚本
 * 导航高亮 · 移动端菜单 · 表单校验 · 新闻时间渲染
 * 零外部依赖，纯原生 JS
 */
(function () {
  'use strict';

  /* ========== 1. 导航高亮 ========== */
  function initNavHighlight() {
    var links = document.querySelectorAll('.navbar__link');
    if (!links.length) return;

    // 取当前页面文件名，默认 index
    var path = window.location.pathname;
    var filename = path.split('/').pop() || 'index.html';

    links.forEach(function (link) {
      var href = link.getAttribute('href') || '';
      var linkFile = href.split('/').pop() || 'index.html';

      // 精确匹配文件名
      if (linkFile === filename) {
        link.classList.add('navbar__link--active');
      } else {
        link.classList.remove('navbar__link--active');
      }
    });
  }

  /* ========== 2. 移动端菜单 ========== */
  function initMobileMenu() {
    var toggle = document.querySelector('.navbar__toggle');
    var menu = document.querySelector('.navbar__menu');
    if (!toggle || !menu) return;

    toggle.addEventListener('click', function () {
      var isOpen = menu.classList.contains('navbar__menu--open');
      if (isOpen) {
        menu.classList.remove('navbar__menu--open');
        toggle.classList.remove('navbar__toggle--open');
        toggle.setAttribute('aria-expanded', 'false');
      } else {
        menu.classList.add('navbar__menu--open');
        toggle.classList.add('navbar__toggle--open');
        toggle.setAttribute('aria-expanded', 'true');
      }
    });

    // 点击菜单项后自动收起
    menu.addEventListener('click', function (e) {
      if (e.target.classList.contains('navbar__link')) {
        menu.classList.remove('navbar__menu--open');
        toggle.classList.remove('navbar__toggle--open');
        toggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  /* ========== 3. 表单校验 ========== */
  function initFormValidation() {
    var form = document.querySelector('.form');
    if (!form) return;

    form.addEventListener('submit', function (e) {
      e.preventDefault();

      var valid = true;

      // 姓名
      var nameInput = form.querySelector('[name="name"]');
      if (nameInput) {
        var nameVal = nameInput.value.trim();
        if (!nameVal) {
          showFieldError(nameInput, '请输入您的姓名');
          valid = false;
        } else if (nameVal.length < 2) {
          showFieldError(nameInput, '姓名至少 2 个字符');
          valid = false;
        } else {
          clearFieldError(nameInput);
        }
      }

      // 邮箱
      var emailInput = form.querySelector('[name="email"]');
      if (emailInput) {
        var emailVal = emailInput.value.trim();
        var emailReg = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailVal) {
          showFieldError(emailInput, '请输入您的邮箱');
          valid = false;
        } else if (!emailReg.test(emailVal)) {
          showFieldError(emailInput, '请输入有效的邮箱地址');
          valid = false;
        } else {
          clearFieldError(emailInput);
        }
      }

      // 留言
      var msgInput = form.querySelector('[name="message"]');
      if (msgInput) {
        var msgVal = msgInput.value.trim();
        if (!msgVal) {
          showFieldError(msgInput, '请输入留言内容');
          valid = false;
        } else if (msgVal.length < 10) {
          showFieldError(msgInput, '留言至少 10 个字符');
          valid = false;
        } else {
          clearFieldError(msgInput);
        }
      }

      if (valid) {
        // 校验通过 — 显示成功提示（无外部依赖，不调用 API）
        var submitBtn = form.querySelector('.form__submit') || form.querySelector('[type="submit"]');
        if (submitBtn) {
          submitBtn.textContent = '已提交 ✓';
          submitBtn.disabled = true;
          submitBtn.style.opacity = '0.6';
        }
        // D-01 修复：清空表单字段并清除所有错误提示
        form.reset();
        var allErrors = form.querySelectorAll('.form__error--visible');
        allErrors.forEach(function (el) { el.classList.remove('form__error--visible'); });
        var allErrorInputs = form.querySelectorAll('.form__input--error, .form__textarea--error');
        allErrorInputs.forEach(function (el) { el.classList.remove('form__input--error', 'form__textarea--error'); });
      }
    });
  }

  function showFieldError(input, message) {
    input.classList.add('form__input--error');
    var errorEl = input.parentElement.querySelector('.form__error');
    if (errorEl) {
      errorEl.textContent = message;
      errorEl.classList.add('form__error--visible');
    }
  }

  function clearFieldError(input) {
    input.classList.remove('form__input--error');
    var errorEl = input.parentElement.querySelector('.form__error');
    if (errorEl) {
      errorEl.classList.remove('form__error--visible');
    }
  }

  /* ========== 4. 新闻时间渲染 ========== */
  function initNewsTimeRender() {
    var items = document.querySelectorAll('[data-news-date]');
    if (!items.length) return;

    var monthNames = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'];

    items.forEach(function (el) {
      var dateStr = el.getAttribute('data-news-date');
      var date = new Date(dateStr);
      if (isNaN(date.getTime())) return;

      var dayEl = el.querySelector('.news-item__day');
      var monthEl = el.querySelector('.news-item__month');

      if (dayEl) {
        dayEl.textContent = date.getDate();
      }
      if (monthEl) {
        monthEl.textContent = monthNames[date.getMonth()] + ' ' + date.getFullYear();
      }
    });
  }

  /* ========== 5. 导航栏滚动效果 ========== */
  function initNavbarScroll() {
    var navbar = document.querySelector('.navbar');
    if (!navbar) return;

    var scrollThreshold = 10;

    window.addEventListener('scroll', function () {
      if (window.scrollY > scrollThreshold) {
        navbar.style.backgroundColor = 'rgba(7,26,51,0.98)';
      } else {
        navbar.style.backgroundColor = 'rgba(11,37,69,0.95)';
      }
    }, { passive: true });
  }

  /* ========== 6. 新闻分类筛选 ========== */
  function initNewsFilter() {
    var filterBtns = document.querySelectorAll('.news-filter__btn');
    var newsItems = document.querySelectorAll('[data-category]');
    if (!filterBtns.length || !newsItems.length) return;

    filterBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var category = btn.getAttribute('data-filter');

        // 更新按钮激活状态
        filterBtns.forEach(function (b) { b.classList.remove('news-filter__btn--active'); });
        btn.classList.add('news-filter__btn--active');

        // 显示/隐藏新闻项
        newsItems.forEach(function (item) {
          if (category === 'all' || item.getAttribute('data-category') === category) {
            item.style.display = '';
          } else {
            item.style.display = 'none';
          }
        });
      });
    });
  }

  /* ========== 7. 加载更多新闻 ========== */
  function initLoadMore() {
    var loadMoreBtn = document.querySelector('.news-load-more');
    if (!loadMoreBtn) return;

    loadMoreBtn.addEventListener('click', function () {
      var hiddenItems = document.querySelectorAll('.news-item--hidden');
      hiddenItems.forEach(function (item) {
        item.classList.remove('news-item--hidden');
      });
      loadMoreBtn.style.display = 'none';
    });
  }

  /* ========== 初始化 ========== */
  function init() {
    initNavHighlight();
    initMobileMenu();
    initFormValidation();
    initNewsTimeRender();
    initNavbarScroll();
    initNewsFilter();
    initLoadMore();
  }

  // DOM 就绪后执行
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
