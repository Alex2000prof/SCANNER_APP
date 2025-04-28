// // Глобальные переменные для административного режима
// let adminMode = false;
// let adminAction = null; // Возможные значения: "delete" или "delete_box"
// let adminPromptActive = false; // Флаг, показывающий, что уже открыто модальное окно
// let adminTimeoutId = null; // Таймер для авто-сброса админ-режима

// function resetAdminMode() {
//   adminMode = false;
//   adminAction = null;
//   adminPromptActive = false;
//   if (adminTimeoutId) {
//     clearTimeout(adminTimeoutId);
//     adminTimeoutId = null;
//   }
//   if (window.AndroidAudio && window.AndroidAudio.setQrEnabled) {
//     window.AndroidAudio.setQrEnabled(false);
//   }
// }

// window.onBarcodeScanned = function(scannedCode) {
//   scannedCode = scannedCode.trim(); // убираем лишние пробелы

//   // Если уже открыто модальное окно – игнорируем входящие сканы
//   if (adminPromptActive) return;

//   // Если не в админ-режиме и отсканирован административный код – активируем режим
//   if (!adminMode && scannedCode === '8011985') {
//     adminPromptActive = true;
//     Swal.fire({
//       title: 'Выберите действие',
//       text: 'Что вы хотите сделать?',
//       icon: 'question',
//       showDenyButton: true,
//       showCancelButton: true,
//       confirmButtonText: 'Удалить скан',
//       denyButtonText: 'Удалить всю коробку',
//       cancelButtonText: 'Отмена'
//     }).then((result) => {
//       if (result.isConfirmed || result.isDenied) {
//         adminMode = true;
//         adminAction = result.isConfirmed ? 'delete' : 'delete_box';
//         // Включаем поддержку QR-кодов для админ-режима
//         if (window.AndroidAudio && window.AndroidAudio.setQrEnabled) {
//           window.AndroidAudio.setQrEnabled(true);
//         }
//         const infoText = result.isConfirmed
//           ? 'Отсканируйте целевой штрихкод для удаления скана.'
//           : 'Отсканируйте штрихкод коробки, чтобы удалить все её сканы.';
//         Swal.fire('Админ режим', infoText, 'info').then(() => {
//           adminPromptActive = false;
//           // Запускаем таймер авто-сброса через 15 секунд, если ничего не отсканировано
//           adminTimeoutId = setTimeout(() => {
//             resetAdminMode();
//           }, 15000);
//         });
//       } else {
//         // Если выбрана отмена
//         adminPromptActive = false;
//       }
//     });
//     return;
//   }

//   // Если мы в административном режиме, следующий скан считается целевым
//   if (adminMode) {
//     // Если пользователь повторно сканирует административный код, игнорируем
//     if (scannedCode === '8011985') return;
    
//     // Останавливаем таймер, т.к. получен целевой скан
//     if (adminTimeoutId) {
//       clearTimeout(adminTimeoutId);
//       adminTimeoutId = null;
//     }
//     adminPromptActive = true;
//     Swal.fire({
//       title: 'Вы уверены?',
//       text: adminAction === 'delete'
//         ? 'Вы действительно хотите удалить этот скан?'
//         : 'Вы действительно хотите удалить все сканы этой коробки?',
//       icon: 'warning',
//       showCancelButton: true,
//       confirmButtonText: 'Да',
//       cancelButtonText: 'Отмена'
//     }).then((result) => {
//       if (result.isConfirmed) {
//         const endpoint = adminAction === 'delete' ? '/delete_scan' : '/delete_box';
//         fetch(endpoint, {
//           method: 'POST',
//           headers: { 'Content-Type': 'application/json' },
//           body: JSON.stringify({ target_code: scannedCode })
//         })
//         .then(res => res.json())
//         .then(data => {
//           if (data.status === 'success') {
//             Swal.fire('Готово!', data.message, 'success');
//           } else {
//             Swal.fire('Ошибка', data.message, 'error');
//           }
//         })
//         .catch(err => {
//           Swal.fire('Ошибка', String(err), 'error');
//         })
//         .finally(() => {
//           // Независимо от результата – сбрасываем режим
//           resetAdminMode();
//         });
//       } else {
//         resetAdminMode();
//       }
//     });
//     return;
//   }

//   // Если не в административном режиме – обычная обработка сканированного кода
//   if (typeof submitScanCode === 'function') {
//     submitScanCode(scannedCode);
//   } else {
//     console.log("Обычный скан: " + scannedCode);
//   }
// };




