export const ROUTES = ['today', 'week', 'homework', 'courses', 'ai', 'manage'];
export const routeFromHash = hash => ROUTES.includes(hash.slice(1)) ? hash.slice(1) : 'today';

// Top-level tabs are alternative views of one app, not a stack of visited pages.
export function replaceRoute(route, browser = window) {
  if (!ROUTES.includes(route)) return false;
  if (browser.location.hash !== `#${route}`) {
    browser.history.replaceState(browser.history.state, '', `#${route}`);
  }
  return true;
}

export function viewportLayout({height, visualHeight = height, offsetTop = 0, scale = 1, editing = false}) {
  // Do not chase the zoomed viewport: this would move navigation across enlarged content.
  const zoomed = Math.abs(scale - 1) > 0.05;
  const covered = zoomed ? 0 : Math.max(0, height - visualHeight - offsetTop);
  return {bottom: Math.round(covered), height: Math.round(zoomed ? height : visualHeight), keyboard: editing && !zoomed && covered > 120};
}

export function watchViewport(browser = window) {
  const root = browser.document.documentElement;
  let frame;
  const update = () => {
    frame = null;
    const viewport = browser.visualViewport;
    const active = browser.document.activeElement;
    const layout = viewportLayout({height: browser.innerHeight, visualHeight: viewport?.height,
      offsetTop: viewport?.offsetTop, scale: viewport?.scale,
      editing: !!active?.matches('input,textarea,[contenteditable="true"]')});
    root.style.setProperty('--viewport-bottom', `${layout.bottom}px`);
    root.style.setProperty('--visible-height', `${layout.height}px`);
    root.classList.toggle('keyboard-open', layout.keyboard);
  };
  const schedule = () => { if (!frame) frame = browser.requestAnimationFrame(update); };
  browser.addEventListener('resize', schedule, {passive:true});
  browser.visualViewport?.addEventListener('resize', schedule, {passive:true});
  browser.visualViewport?.addEventListener('scroll', schedule, {passive:true});
  browser.document.addEventListener('focusin', schedule);
  browser.document.addEventListener('focusout', schedule);
  update();
}
