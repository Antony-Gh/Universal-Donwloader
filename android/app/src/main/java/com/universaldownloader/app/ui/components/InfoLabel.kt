package com.universaldownloader.app.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.universaldownloader.app.ui.theme.AccentSky
import com.universaldownloader.app.ui.theme.SurfaceCard
import com.universaldownloader.app.ui.theme.TextMuted
import com.universaldownloader.app.ui.theme.TextPrimary
import com.universaldownloader.app.ui.theme.TextSecondary

@Composable
fun InfoLabel(
    title: String,
    explanation: String,
    modifier: Modifier = Modifier,
    fontSize: TextUnit = 13.sp,
    fontWeight: FontWeight = FontWeight.Medium,
    color: Color = TextSecondary,
) {
    var showDialog by remember { mutableStateOf(false) }

    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            text = title,
            color = color,
            fontSize = fontSize,
            fontWeight = fontWeight,
        )
        Icon(
            imageVector = Icons.Outlined.Info,
            contentDescription = "Info about $title",
            tint = TextMuted,
            modifier = Modifier
                .size(16.dp)
                .clickable { showDialog = true },
        )
    }

    if (showDialog) {
        AlertDialog(
            onDismissRequest = { showDialog = false },
            containerColor = SurfaceCard,
            shape = RoundedCornerShape(14.dp),
            title = {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Icon(
                        imageVector = Icons.Outlined.Info,
                        contentDescription = null,
                        tint = AccentSky,
                        modifier = Modifier.size(20.dp),
                    )
                    Text(
                        text = title,
                        color = TextPrimary,
                        fontWeight = FontWeight.Bold,
                        fontSize = 17.sp,
                    )
                }
            },
            text = {
                Text(
                    text = explanation,
                    color = TextSecondary,
                    fontSize = 14.sp,
                    lineHeight = 20.sp,
                )
            },
            confirmButton = {
                TextButton(onClick = { showDialog = false }) {
                    Text("Got it", color = AccentSky, fontWeight = FontWeight.SemiBold)
                }
            },
        )
    }
}
