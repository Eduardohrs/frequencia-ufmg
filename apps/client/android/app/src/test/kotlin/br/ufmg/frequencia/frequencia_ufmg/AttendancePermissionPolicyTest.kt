package br.ufmg.frequencia.frequencia_ufmg

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AttendancePermissionPolicyTest {
    @Test fun `downloads prompt once and respect earlier refusal and pending requests`() {
        assertTrue(AttendancePermissionPolicy.askForDownloadNotifications(36, false, false, false, false))
        assertFalse(AttendancePermissionPolicy.askForDownloadNotifications(32, false, false, false, false))
        assertFalse(AttendancePermissionPolicy.askForDownloadNotifications(36, true, false, false, false))
        assertFalse(AttendancePermissionPolicy.askForDownloadNotifications(36, false, true, false, false))
        assertFalse(AttendancePermissionPolicy.askForDownloadNotifications(36, false, false, true, false))
        assertFalse(AttendancePermissionPolicy.askForDownloadNotifications(36, false, false, false, true))
    }
    @Test fun `never requests an already granted permission or loops after permanent refusal`() {
        assertFalse(AttendancePermissionPolicy.requestable(true, false, false))
        assertFalse(AttendancePermissionPolicy.requestable(true, true, true))
        assertTrue(AttendancePermissionPolicy.requestable(false, false, false))
        assertTrue(AttendancePermissionPolicy.requestable(false, true, true))
        assertFalse(AttendancePermissionPolicy.requestable(false, true, false))
    }
    @Test fun `background access is separate on Android 10 and later and never substitutes foreground access`() {
        assertTrue(AttendancePermissionPolicy.backgroundGranted(true, 28, false))
        assertFalse(AttendancePermissionPolicy.backgroundGranted(true, 29, false))
        assertFalse(AttendancePermissionPolicy.backgroundGranted(true, 36, false))
        assertTrue(AttendancePermissionPolicy.backgroundGranted(true, 36, true))
        assertFalse(AttendancePermissionPolicy.backgroundGranted(false, 28, true))
        assertFalse(AttendancePermissionPolicy.backgroundGranted(false, 36, true))
    }
}
