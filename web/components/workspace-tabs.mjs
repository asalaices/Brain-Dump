// SPDX-License-Identifier: AGPL-3.0-only
export function bindWorkspaceTabs({tabs, panels}) {
  if (tabs.length !== panels.length || !tabs.length) throw new TypeError('Tabs require matching panels.');
  function activate(index, focus = false) {
    tabs.forEach((tab, current) => {
      const selected = current === index;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      panels[current].hidden = !selected;
    });
    if (focus) tabs[index].focus();
  }
  const handlers = tabs.map((tab, index) => {
    const click = () => activate(index);
    const keydown = event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      else return;
      event.preventDefault();
      activate(next, true);
    };
    tab.addEventListener('click', click);
    tab.addEventListener('keydown', keydown);
    return {click, keydown};
  });
  activate(0);
  return () => tabs.forEach((tab, index) => {
    tab.removeEventListener('click', handlers[index].click);
    tab.removeEventListener('keydown', handlers[index].keydown);
  });
}
