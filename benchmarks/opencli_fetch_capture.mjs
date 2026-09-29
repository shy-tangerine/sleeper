import fs from 'node:fs';

const output = process.env.OPENCLI_CAPTURE_FILE;
const originalFetch = globalThis.fetch;
globalThis.fetch = async (input, init = {}) => {
  const url = typeof input === 'string' ? input : input?.url;
  const requestText = typeof init.body === 'string' ? init.body : '';
  const response = await originalFetch(input, init);
  if (output && url?.endsWith('/command')) {
    const responseText = await response.clone().text();
    fs.appendFileSync(output, JSON.stringify({requestText, responseText, status: response.status}) + '\n');
  }
  return response;
};
