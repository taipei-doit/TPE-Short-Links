/**
 * 公開頁（聲明頁、查核頁、QR 產生器）的視覺語彙。
 *
 * 方向：公文的莊重＋捷運指標的清晰。明體大標、條文式編號、細線分節，
 * 唯一的亮色是市徽四色的簽名色條；不用卡片陰影與漸層裝飾。
 */

/** 明體大標：Noto Serif TC 由 index.html 載入，未載入前退回系統明體。 */
export const SERIF_TC = '"Noto Serif TC", "PMingLiU", "MingLiU", serif';

/** 公開頁底色：偏紙感的白，取代管理端的灰藍漸層。 */
export const PAPER = '#FAFBFC';

/** 標題墨色，比品牌藍更沉。 */
export const INK = '#16324A';

/** 市徽四色（紅黃綠藍筆刷的沉穩版），只用在簽名色條。 */
export const EMBLEM_COLORS = ['#C64B4B', '#DFA92E', '#2F9464', '#2B6CB0'];
