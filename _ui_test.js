(function () {
          try {
            var errs = window.__mkEarlyErrors || [];
            var menubar = document.getElementById('menubar');
            var mbVisible = false;
            if (menubar) {
              var s = getComputedStyle(menubar);
              mbVisible = s.display !== 'none' && s.visibility !== 'hidden';
            }
            return JSON.stringify({
              initialized: !!window.__markEaseInitialized,
              initStage: window.__mkInitStage || 'none',
              initError: window.__mkInitError || null,
              hasApi: !!(window.pywebview && window.pywebview.api),
              toolbarButtons: document.querySelectorAll('#toolbar .tb-btn').length,
              editorReady: !!document.querySelector('.cm-editor'),
              previewReady: !!document.querySelector('#preview'),
              menubarVisible: mbVisible,
              nativeMenuExpected: document.documentElement.classList.contains('platform-mac'),
              readyState: document.readyState,
              earlyErrors: errs.slice(0, 10),
              fuzzyProbe: (function () {
                try {
                  if (!window.MKTestLoad || !window.PreviewSearch) return null;
                  var cases = [
                    'foo **bar**',
                    '> foo **bar**',
                    '- foo **bar**',
                    'foo *bar*',
                    'foo `bar`',
                    'foo [bar](https://example.com)'
                  ];
                  var out = [];
                  for (var i = 0; i < cases.length; i++) {
                    var md = cases[i];
                    window.MKTestLoad(md);
                    var fm = window.PreviewSearch.findFuzzyMatches(
                      md, 'foo bar', false);
                    out.push({ md: md, count: fm.length,
                               first: fm.length ? fm[0] : null });
                  }
                  // 强制走源码级兜底（模拟预览块不可用）
                  try {
                    window.MKTestLoad('foo **bar**');
                    var pv = document.getElementById('preview');
                    if (pv) pv.innerHTML = '';
                    window.PreviewSearch.onPreviewRendered();
                    var fm2 = window.PreviewSearch.findFuzzyMatches(
                      'foo **bar**', 'foo bar', false);
                    out.push({ md: 'source-fallback', count: fm2.length,
                               first: fm2.length ? fm2[0] : null });
                  } catch (e2) {
                    out.push({ md: 'source-fallback', error: String(e2) });
                  }
                  return out;
                } catch (e) { return { error: String(e) }; }
              })(),
              ua: navigator.userAgent
            });
          } catch (e) {
            return JSON.stringify({ fatal: String(e) });
          }
        })()