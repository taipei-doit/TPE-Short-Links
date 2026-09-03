import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';

import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { DatesProvider } from '@mantine/dates';
import { Notifications } from '@mantine/notifications';
import { ModalsProvider } from '@mantine/modals';
import { BrowserRouter } from 'react-router-dom';
import 'dayjs/locale/zh-tw';

import { AuthProvider } from './auth/AuthContext';
import { App } from './routes/App';

// 裸的 Hosting 網域不對外使用：一律轉到正式的管理網域（同路徑）。
// 這只是引導，真正的門是登入與 QR PIN。
const rawHosts = ['url-taipei.web.app', 'url-taipei.firebaseapp.com'];
if (rawHosts.includes(window.location.hostname)) {
  window.location.replace(
    `https://admin.url.taipei${window.location.pathname}${window.location.search}${window.location.hash}`,
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider
      defaultColorScheme="light"
      theme={{
        primaryColor: 'blue',
        defaultRadius: 'md',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", "Helvetica Neue", Arial, sans-serif',
        headings: {
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", "Helvetica Neue", Arial, sans-serif',
          fontWeight: '600',
        },
      }}
    >
      <DatesProvider settings={{ locale: 'zh-tw' }}>
        <Notifications position="top-right" />
        <ModalsProvider>
          <BrowserRouter>
            <AuthProvider>
              <App />
            </AuthProvider>
          </BrowserRouter>
        </ModalsProvider>
      </DatesProvider>
    </MantineProvider>
  </React.StrictMode>,
);

