// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.app.admin.DeviceAdminReceiver

/**
 * The device-admin component that lets a phone kept as a prop make the app
 * its device owner, so kiosk mode needs no confirmation (KioskPlugin). It
 * asks for no policies (res/xml/device_admin.xml).
 */
class AtalaiaAdminReceiver : DeviceAdminReceiver()
