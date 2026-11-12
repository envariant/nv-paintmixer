import { expect, test } from '@playwright/test'

test('mix a library colour on the simulated machine', async ({ page }) => {
  await page.goto('/library')
  await page.getByRole('list', { name: 'Colours' }).getByRole('listitem', { name: 'Lagoon Teal' }).click()
  await page.getByTestId('mix-this').click()
  await expect(page).toHaveURL(/\/mix\?color=\d+/)

  const dispense = page.getByTestId('dispense')
  await expect(dispense).toHaveText(/Dispense Mix A · SGD \d+\.\d\d/, { timeout: 30_000 })
  await expect(page.getByRole('list', { name: 'Ways to mix it' }).getByRole('listitem')).toHaveCount(3)
  await dispense.click()

  // the run screen: the first pour is measured, then the job is done or waits for a decision
  await expect(page).toHaveURL(/job=\d+/)
  await expect(page.getByRole('radiogroup', { name: 'Rounds' })).toContainText('First pour', { timeout: 30_000 })
  const accept = page.getByTestId('accept')
  if (await accept.isVisible()) await accept.click()
  await expect(page.getByRole('button', { name: 'New mix' })).toBeVisible({ timeout: 30_000 })

  // the machine popover lists the finished job
  await page.getByTestId('machine-pill').click()
  await expect(page.getByRole('list', { name: 'Recent jobs' })).toContainText('Lagoon Teal')

  // Export log downloads the job log as CSV
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByTestId('export-log').click()])
  expect(download.suggestedFilename()).toBe('paintmixer-jobs.csv')
  const csv = await (await download.createReadStream()).toArray()
  const lines = Buffer.concat(csv).toString('utf8').trim().split('\n')
  expect(lines[0]).toBe('id,name,created,status,rounds,final_de,poured_ml,paints')
  expect(lines[1]).toContain('Lagoon Teal')
})

test('models rack and settings', async ({ page }) => {
  await page.goto('/models')
  const rack = page.getByRole('list', { name: 'Paints in this model' })
  await expect(rack.getByRole('listitem')).toHaveCount(5)
  await expect(rack).toContainText('Yellow (Arylide)')
  await expect(rack).toContainText('Channel')

  await page.goto('/settings')
  const tolerance = page.getByLabel('Accept tolerance (ΔE)')
  await tolerance.fill('0.8')
  await tolerance.press('Enter')
  await expect(page.getByText('1 unsaved change')).toBeVisible()
  await page.getByTestId('save-settings').click()
  await expect(page.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible()
})
