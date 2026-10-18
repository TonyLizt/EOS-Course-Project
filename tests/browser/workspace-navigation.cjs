// 三步布局的真实导航；保留原测试的业务断言，不用脚本强行取消 hidden。
exports.step = async (page, number) => {
  const route = page.locator('nav [data-console-route="create"]');
  if (await route.count()) await route.click();
  const button = page.locator(`[data-workspace-step="${number}"]`);
  if (await button.count()) await button.click();
};
exports.addAlgorithms = async page => {
  const route = page.locator('nav [data-console-route="records"]');
  if (await route.count()) await route.click();
  const disclosure = page.locator('details.add-algorithms');
  if (await disclosure.count() && !(await disclosure.getAttribute('open') !== null))
    await disclosure.locator('summary').click();
};
