import { Anchor, Breadcrumbs, Text } from '@mantine/core';
import { Link } from 'react-router-dom';

/** 路徑連結列（麵包屑）：無障礙檢核 HM3240800E 要求的所在位置導覽。 */
export function Crumbs({ current }: { current: string }) {
  return (
    <nav aria-label="路徑連結列">
      <Breadcrumbs separator="／" separatorMargin={8}>
        <Anchor component={Link} to="/" size="sm" c="brand.8" fw={500}>
          首頁
        </Anchor>
        <Text size="sm" c="dark.5" aria-current="page">
          {current}
        </Text>
      </Breadcrumbs>
    </nav>
  );
}
