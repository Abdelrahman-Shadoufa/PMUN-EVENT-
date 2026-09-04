import base64
import io
import json
import os
import re
import secrets
import time
import cv2
import flet as ft
import pywhatkit as pwk
import qrcode
from supabase import create_client, Client

BLANK_IMAGE_SRC = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVOR5CYII="

# ==========================================
# SUPABASE CONFIGURATION (CLOUD DATABASE)
# ==========================================
SUPABASE_URL = "https://prywhefbokladpghxnlw.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InByeXdoZWZib2tsYWRwZ2h4bmx3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg1MDE1MDQsImV4cCI6MjEwNDA3NzUwNH0.3o5zyp2yDZr8KtmMy5CPIUpE4MQakhJdnf2vEgABrzE"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


class ConcertApp:

    def add_ticket(self, ticket_id: str, name: str, days: int):
        redemptions = {str(day): False for day in range(1, days + 1)}
        supabase.table("tickets").insert(
            {
                "ticket_id": ticket_id,
                "name": name,
                "days": days,
                "redemptions": redemptions,
            }
        ).execute()

    def get_all_tickets(self):
        response = supabase.table("tickets").select("*").execute()
        rows = response.data

        tickets = {}
        for row in rows:
            t_id = row["ticket_id"]
            redemptions_data = row["redemptions"]
            
            # Handle string vs dict responses from JSON fields
            if isinstance(redemptions_data, str):
                redemptions_dict = json.loads(redemptions_data)
            else:
                redemptions_dict = redemptions_data

            tickets[t_id] = {
                "name": row["name"],
                "days": row["days"],
                "redemptions": {
                    int(k): v for k, v in redemptions_dict.items()
                },
            }
        return tickets

    def update_redemption(self, ticket_id: str, day: int, value: bool):
        tickets = self.get_all_tickets()
        if ticket_id in tickets:
            redemptions = tickets[ticket_id]["redemptions"]
            redemptions[day] = value
            
            # Format keys back to string for JSON serialization
            formatted_redemptions = {str(k): v for k, v in redemptions.items()}

            supabase.table("tickets").update(
                {"redemptions": formatted_redemptions}
            ).eq("ticket_id", ticket_id).execute()

    def delete_ticket(self, ticket_id: str):
        supabase.table("tickets").delete().eq("ticket_id", ticket_id).execute()

    def generate_qr_base64_and_bytes(self, data_str: str):
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=8,
            border=2,
        )
        qr.add_data(data_str)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        png_bytes = buffer.getvalue()
        b64_str = base64.b64encode(png_bytes).decode("utf-8")
        return b64_str, png_bytes


def sanitize_filename(name: str) -> str:
    clean_name = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    clean_name = clean_name.replace(" ", "_")
    return clean_name if clean_name else "ticket_qr"


def main(page: ft.Page):
    # Mobile Layout & Theme Configurations
    page.title = "Concert Pass Manager (Cloud Sync)"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#11111B"
    page.padding = 12
    page.window.width = 390
    page.window.height = 840
    page.window.resizable = True
    page.scroll = ft.ScrollMode.AUTO

    app_state = ConcertApp()

    current_pass_info = {"ticket_id": "", "name": "", "png_bytes": None}

    # ==========================================
    # SECTION 1: ISSUE PASS & GENERATE QR
    # ==========================================
    name_input = ft.TextField(
        label="Attendee Name",
        hint_text="e.g. John Doe",
        prefix_icon=ft.Icons.PERSON_OUTLINED,
        border_radius=10,
        border_color="#313244",
        focused_border_color="#89B4FA",
    )
    phone_input = ft.TextField(
        label="Phone Number with Country Code",
        hint_text="e.g. +201234567890",
        prefix_icon=ft.Icons.PHONE_OUTLINED,
        border_radius=10,
        border_color="#313244",
        focused_border_color="#89B4FA",
    )
    days_dropdown = ft.Dropdown(
        label="Concert Duration",
        value="2",
        border_radius=10,
        border_color="#313244",
        focused_border_color="#89B4FA",
        options=[
            ft.dropdown.Option("1", "1 Day Pass"),
            ft.dropdown.Option("2", "2 Days Pass"),
            ft.dropdown.Option("3", "3 Days Pass"),
            ft.dropdown.Option("4", "4 Days Pass"),
            ft.dropdown.Option("5", "5 Days Pass"),
        ],
    )

    qr_image = ft.Image(
        src=BLANK_IMAGE_SRC, width=180, height=180, visible=False
    )
    issue_status = ft.Text(size=13, weight=ft.FontWeight.W_500)

    share_whatsapp_btn = ft.ElevatedButton(
        "WhatsApp",
        icon=ft.Icons.SEND_ROUNDED,
        bgcolor="#25D366",
        color=ft.Colors.WHITE,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
        visible=False,
    )
    save_image_btn = ft.OutlinedButton(
        "Save Image",
        icon=ft.Icons.DOWNLOAD_ROUNDED,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=10),
            side=ft.BorderSide(1, "#89B4FA"),
        ),
        visible=False,
    )

    def issue_ticket_click(e):
        attendee_name = name_input.value.strip()
        if not attendee_name:
            issue_status.value = "Please enter an attendee name."
            issue_status.color = "#F38BA8"
            page.update()
            return

        random_suffix = secrets.token_hex(2).upper()
        ticket_id = f"TICK-{int(time.time())}-{random_suffix}"
        duration = int(days_dropdown.value)

        try:
            app_state.add_ticket(ticket_id, attendee_name, duration)
        except Exception as err:
            issue_status.value = f"Cloud Error: {str(err)}"
            issue_status.color = "#F38BA8"
            page.update()
            return

        b64_str, png_bytes = app_state.generate_qr_base64_and_bytes(ticket_id)
        qr_image.src = f"data:image/png;base64,{b64_str}"
        qr_image.visible = True

        current_pass_info["ticket_id"] = ticket_id
        current_pass_info["name"] = attendee_name
        current_pass_info["png_bytes"] = png_bytes

        issue_status.value = f"Pass Synced to Cloud!\nID: {ticket_id}"
        issue_status.color = "#A6E3A1"

        share_whatsapp_btn.visible = True
        save_image_btn.visible = True

        name_input.value = ""
        refresh_manual_list()
        page.update()

    def send_whatsapp_click(e):
        phone_number = phone_input.value.strip()
        if not phone_number or not phone_number.startswith("+"):
            issue_status.value = "Please enter valid number with '+' prefix."
            issue_status.color = "#F38BA8"
            page.update()
            return

        if not current_pass_info["png_bytes"]:
            return

        file_title = sanitize_filename(current_pass_info["name"])
        image_path = f"{file_title}.png"
        with open(image_path, "wb") as f:
            f.write(current_pass_info["png_bytes"])

        abs_image_path = os.path.abspath(image_path)
        caption = f"Hello {current_pass_info['name']},\nHere is your official Concert Pass ({current_pass_info['ticket_id']})!"

        issue_status.value = "Opening WhatsApp Web..."
        issue_status.color = "#89B4FA"
        page.update()

        try:
            pwk.sendwhats_image(
                receiver=phone_number,
                img_path=abs_image_path,
                caption=caption,
                wait_time=15,
                tab_close=True,
            )
            issue_status.value = f"Image sent successfully to {phone_number}!"
            issue_status.color = "#A6E3A1"
        except Exception as err:
            issue_status.value = f"WhatsApp Error: {str(err)}"
            issue_status.color = "#F38BA8"

        page.update()

    def save_qr_click(e):
        if not current_pass_info["png_bytes"]:
            return

        file_title = sanitize_filename(current_pass_info["name"])
        filename = f"{file_title}.png"

        with open(filename, "wb") as f:
            f.write(current_pass_info["png_bytes"])

        abs_path = os.path.abspath(filename)
        issue_status.value = f"Saved locally:\n{abs_path}"
        issue_status.color = "#89B4FA"
        page.update()

    share_whatsapp_btn.on_click = send_whatsapp_click
    save_image_btn.on_click = save_qr_click

    issue_card = ft.Container(
        content=ft.Column(
            [
                ft.Text("Issue Pass", size=18, weight=ft.FontWeight.BOLD, color="#CDD6F4"),
                name_input,
                phone_input,
                days_dropdown,
                ft.ElevatedButton(
                    "Generate Pass",
                    icon=ft.Icons.QR_CODE_2_ROUNDED,
                    bgcolor="#89B4FA",
                    color="#11111B",
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
                    on_click=issue_ticket_click,
                ),
            ],
            spacing=12,
        ),
        padding=14,
        bgcolor="#1E1E2E",
        border_radius=14,
        border=ft.Border.all(1, "#313244"),
    )

    qr_display_card = ft.Container(
        content=ft.Column(
            [
                issue_status,
                ft.Container(
                    content=qr_image,
                    alignment=ft.Alignment(0, 0),
                    padding=8,
                    bgcolor="#FFFFFF",
                    border_radius=12,
                ),
                ft.Row(
                    controls=[share_whatsapp_btn, save_image_btn],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=8,
                    wrap=True,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
        ),
        padding=14,
        bgcolor="#1E1E2E",
        border_radius=14,
        border=ft.Border.all(1, "#313244"),
    )

    issue_view = ft.Column(
        [issue_card, qr_display_card],
        spacing=14,
        visible=True,
    )

    # ==========================================
    # SECTION 2: OPENCV QR CODE SCANNER
    # ==========================================
    scan_status = ft.Text(size=14, weight=ft.FontWeight.BOLD)
    scan_details = ft.Column(spacing=8)
    day_select = ft.Dropdown(
        label="Scan Target Day",
        value="1",
        border_radius=10,
        border_color="#313244",
        options=[ft.dropdown.Option(str(i), f"Day {i}") for i in range(1, 6)],
    )

    def process_scanned_id(scanned_id: str):
        scan_details.controls.clear()
        all_tickets = app_state.get_all_tickets()

        if scanned_id not in all_tickets:
            scan_status.value = f"Invalid Ticket ID: {scanned_id}"
            scan_status.color = "#F38BA8"
            page.update()
            return

        ticket = all_tickets[scanned_id]
        current_day = int(day_select.value)

        if current_day > ticket["days"]:
            scan_status.value = f"Ticket valid for {ticket['days']} day(s) only."
            scan_status.color = "#FAB387"
        elif ticket["redemptions"].get(current_day, False):
            scan_status.value = f"ALREADY REDEEMED (Day {current_day})"
            scan_status.color = "#F38BA8"
        else:
            app_state.update_redemption(scanned_id, current_day, True)
            ticket["redemptions"][current_day] = True
            scan_status.value = f"SUCCESS: Day {current_day} Redeemed!"
            scan_status.color = "#A6E3A1"
            refresh_manual_list()

        scan_details.controls.append(
            ft.Text(f"Attendee: {ticket['name']}", size=15, weight=ft.FontWeight.BOLD)
        )
        scan_details.controls.append(
            ft.Text(f"ID: {scanned_id}", size=12, color="#A6ADC8")
        )

        status_rows = []
        for d in range(1, ticket["days"] + 1):
            taken = ticket["redemptions"][d]
            icon = ft.Icons.CHECK_CIRCLE_ROUNDED if taken else ft.Icons.CANCEL_ROUNDED
            color = "#A6E3A1" if taken else "#F38BA8"
            status_rows.append(
                ft.Row(
                    [
                        ft.Icon(icon, color=color, size=18),
                        ft.Text(
                            f"Day {d}: {'Meal Redeemed' if taken else 'Not Claimed'}",
                            size=13,
                        ),
                    ]
                )
            )

        scan_details.controls.append(ft.Column(status_rows, spacing=4))
        page.update()

    def start_camera_scan(e):
        cap = cv2.VideoCapture(0)
        detector = cv2.QRCodeDetector()
        scanned_code = None

        scan_status.value = "Camera active... Point at QR Code."
        scan_status.color = "#89B4FA"
        page.update()

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            data, bbox, _ = detector.detectAndDecode(frame)
            if data:
                scanned_code = data
                break

            cv2.imshow("Concert Meal Scanner (Press Q to cancel)", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        cap.release()
        cv2.destroyAllWindows()

        if scanned_code:
            process_scanned_id(scanned_code)
        else:
            scan_status.value = "Scanning cancelled."
            scan_status.color = "#A6ADC8"
            page.update()

    scan_view = ft.Container(
        content=ft.Column(
            [
                ft.Text("Redemption Scanner", size=18, weight=ft.FontWeight.BOLD, color="#CDD6F4"),
                day_select,
                ft.ElevatedButton(
                    "Launch Camera Scanner",
                    icon=ft.Icons.CAMERA_ALT_ROUNDED,
                    bgcolor="#89B4FA",
                    color="#11111B",
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
                    on_click=start_camera_scan,
                ),
                ft.Divider(color="#313244"),
                scan_status,
                scan_details,
            ],
            spacing=14,
        ),
        padding=14,
        bgcolor="#1E1E2E",
        border_radius=14,
        border=ft.Border.all(1, "#313244"),
        visible=False,
    )

    # ==========================================
    # SECTION 3: MANUAL LOOKUP, OVERRIDE & IN-APP POPUP
    # ==========================================
    manual_search = ft.TextField(
        label="Search Attendee or Ticket ID",
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        border_radius=10,
        border_color="#313244",
        focused_border_color="#89B4FA",
        on_change=lambda e: refresh_manual_list(),
    )
    manual_list = ft.Column(spacing=10)

    popup_title = ft.Text("", size=16, weight=ft.FontWeight.BOLD, color="#CDD6F4")
    popup_subtitle = ft.Text("", size=12, color="#A6ADC8")
    popup_qr_img = ft.Image(src=BLANK_IMAGE_SRC, width=180, height=180)
    popup_save_btn = ft.OutlinedButton(
        "Save Image",
        icon=ft.Icons.DOWNLOAD_ROUNDED,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=8),
            side=ft.BorderSide(1, "#89B4FA"),
        ),
    )

    popup_card = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        popup_title,
                        ft.IconButton(
                            icon=ft.Icons.CLOSE_ROUNDED,
                            icon_color="#F38BA8",
                            tooltip="Close Note",
                            on_click=lambda e: close_in_app_popup(),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                popup_subtitle,
                ft.Container(
                    content=popup_qr_img,
                    bgcolor="#FFFFFF",
                    padding=8,
                    border_radius=12,
                    alignment=ft.Alignment(0, 0),
                ),
                ft.Row([popup_save_btn], alignment=ft.MainAxisAlignment.CENTER),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        ),
        padding=14,
        bgcolor="#181825",
        border_radius=14,
        border=ft.Border.all(1.5, "#89B4FA"),
        visible=False,
    )

    def close_in_app_popup():
        popup_card.visible = False
        page.update()

    def toggle_redemption(ticket_id: str, day: int, current_val: bool):
        app_state.update_redemption(ticket_id, day, not current_val)
        refresh_manual_list()

    def delete_ticket(ticket_id: str):
        app_state.delete_ticket(ticket_id)
        refresh_manual_list()

    def open_qr_dialog(ticket_id: str, name: str):
        b64_str, png_bytes = app_state.generate_qr_base64_and_bytes(ticket_id)

        popup_title.value = f"Pass: {name}"
        popup_subtitle.value = f"ID: {ticket_id}"
        popup_qr_img.src = f"data:image/png;base64,{b64_str}"

        def save_action(e):
            filename = f"{sanitize_filename(name)}.png"
            with open(filename, "wb") as f:
                f.write(png_bytes)
            popup_subtitle.value = f"Saved locally: {filename}"
            popup_subtitle.color = "#A6E3A1"
            page.update()

        popup_save_btn.on_click = save_action
        popup_card.visible = True
        page.update()

    def refresh_manual_list():
        manual_list.controls.clear()
        query = manual_search.value.lower().strip() if manual_search.value else ""
        all_tickets = app_state.get_all_tickets()

        for t_id, data in all_tickets.items():
            if query and query not in t_id.lower() and query not in data["name"].lower():
                continue

            day_chips = []
            for day_num, taken in data["redemptions"].items():
                chip_color = "#254636" if taken else "#4A252C"
                text_color = "#A6E3A1" if taken else "#F38BA8"
                status_txt = f"Day {day_num}: {'Claimed' if taken else 'Pending'}"
                day_chips.append(
                    ft.Container(
                        content=ft.Text(status_txt, size=11, color=text_color, weight=ft.FontWeight.W_500),
                        bgcolor=chip_color,
                        padding=ft.Padding.symmetric(horizontal=8, vertical=5),
                        border_radius=6,
                        on_click=lambda e, tid=t_id, d=day_num, v=taken: toggle_redemption(
                            tid, d, v
                        ),
                    )
                )

            card = ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(ft.Icons.CONFIRMATION_NUMBER_OUTLINED, color="#89B4FA", size=18),
                                        ft.Column(
                                            [
                                                ft.Text(data["name"], weight=ft.FontWeight.BOLD, color="#CDD6F4", size=14),
                                                ft.Text(f"ID: {t_id} • {data['days']} Day Pass", size=11, color="#A6ADC8"),
                                            ],
                                            spacing=1,
                                        ),
                                    ],
                                    spacing=8,
                                ),
                                ft.Row(
                                    [
                                        ft.IconButton(
                                            icon=ft.Icons.REFRESH_ROUNDED,
                                            icon_color="#A6ADC8",
                                            tooltip="Sync Cloud",
                                            on_click=lambda e: refresh_manual_list(),
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.QR_CODE_ROUNDED,
                                            icon_color="#89B4FA",
                                            tooltip="View QR Pass",
                                            on_click=lambda e, tid=t_id, n=data["name"]: open_qr_dialog(tid, n),
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
                                            icon_color="#F38BA8",
                                            tooltip="Delete Record",
                                            on_click=lambda e, tid=t_id: delete_ticket(tid),
                                        ),
                                    ],
                                    spacing=0,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Text("Tap status tag to toggle:", size=10, color="#6C7086"),
                        ft.Row(day_chips, wrap=True, spacing=6),
                    ],
                    spacing=8,
                ),
                padding=12,
                bgcolor="#1E1E2E",
                border_radius=12,
                border=ft.Border.all(1, "#313244"),
            )
            manual_list.controls.append(card)

        page.update()

    manual_view = ft.Column(
        [
            ft.Row(
                [
                    ft.Text("Manual Control Panel", size=18, weight=ft.FontWeight.BOLD, color="#CDD6F4"),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH_ROUNDED,
                        icon_color="#89B4FA",
                        tooltip="Refresh All Records from Cloud",
                        on_click=lambda e: refresh_manual_list(),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            popup_card,
            manual_search,
            manual_list,
        ],
        spacing=12,
        visible=False,
    )

    # ==========================================
    # NAVIGATION SYSTEM
    # ==========================================
    all_views = [issue_view, scan_view, manual_view]

    def create_nav_button(text, icon, index):
        return ft.Container(
            content=ft.Row(
                [ft.Icon(icon, size=16), ft.Text(text, size=11, weight=ft.FontWeight.W_600)],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=4,
            ),
            padding=ft.Padding.symmetric(vertical=8, horizontal=10),
            border_radius=8,
            on_click=lambda e: switch_tab(index),
        )

    btn_issue = create_nav_button("Issue", ft.Icons.QR_CODE_ROUNDED, 0)
    btn_scan = create_nav_button("Scan", ft.Icons.CAMERA_ALT_ROUNDED, 1)
    btn_manual = create_nav_button("Records", ft.Icons.LIST_ALT_ROUNDED, 2)
    nav_buttons = [btn_issue, btn_scan, btn_manual]

    def switch_tab(index: int):
        for i, view in enumerate(all_views):
            view.visible = i == index

        for i, btn in enumerate(nav_buttons):
            if i == index:
                btn.bgcolor = "#89B4FA"
                btn.content.controls[0].color = "#11111B"
                btn.content.controls[1].color = "#11111B"
            else:
                btn.bgcolor = "transparent"
                btn.content.controls[0].color = "#A6ADC8"
                btn.content.controls[1].color = "#A6ADC8"

        if index == 2:
            refresh_manual_list()

        page.update()

    nav_container = ft.Container(
        content=ft.Row(nav_buttons, alignment=ft.MainAxisAlignment.SPACE_EVENLY),
        bgcolor="#181825",
        padding=4,
        border_radius=12,
        border=ft.Border.all(1, "#313244"),
    )

    page.add(
        nav_container,
        ft.Container(height=6),
        ft.Column(all_views),
    )

    switch_tab(0)


if __name__ == "__main__":
    ft.app(target=main)