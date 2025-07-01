# Telegram Points & Rewards Bot (Check Stat)

## General Overview
This project is an advanced Telegram bot designed to incentivize user engagement by rewarding them for growing Telegram groups. The bot awards points to users who add new members to designated groups. Once a certain threshold of points is reached, they are converted into redeemable "prize codes," which can be exchanged for cash rewards.

The bot is architected with a clean separation of concerns: a user-facing panel for all members and a powerful, private administrative panel for monitoring, request management, and analytics.

---

## Key Features

The bot provides a comprehensive suite of features for both standard users and administrators.

### 💎 Features for Standard Users
Mandatory Channel Membership: To begin interacting with the bot, users are required to join a specified notification channel.

Secure, Multi-Step Registration: Users complete a guided registration process, providing essential details like their phone number, full name, and banking information (card number and IBAN/Sheba) needed for settlements.

#### Point Earning System:

Users earn 1 point for every new, unique member they add to the target groups.

The system intelligently prevents duplicate point allocation for members who have already been added.

Automatic Point-to-Code Conversion: For every 100 points accumulated, a cash prize code is automatically generated and assigned to the user.

#### User Dashboard:

🏆 My Points: View total accumulated points and the number of prize codes received.

🎫 My Codes: See a list of all prize codes along with their current status (Settled / Awaiting Settlement).

✏️ Edit Information: Users can modify their registration details at any time.

#### Settlement Requests:

💰 From the main menu, users can request a settlement for any of their unsettled prize codes.

These requests are queued and sent to the admin panel for review and approval.

#### Online Support:

📞 Users can create support tickets directly through the bot to communicate with administrators.

Admin replies are delivered back to the user via the bot.

#### Comprehensive Guide:

❓ A detailed help section explains every aspect of how to use the bot.

### 👑 Features for Administrators

Dedicated Admin Panel: By sending the /admin command, administrators gain access to a full-featured management menu.

Overall Statistics 📊: A real-time dashboard displaying key metrics, including the number of registered users, total codes issued, pending settlement requests, and open support tickets.

Excel Export of User Data 📄: The ability to generate and receive a complete .xlsx file containing all registered user information.

Settlement Request Management 💳:

View a list of all pending settlement requests.

Review full user details, including their banking information.

A secure approval workflow: after making the payment, the admin uploads a proof of payment receipt to the bot and then approves the request. The receipt is sent to the user along with the confirmation message.

Support Ticket Management 📮: View user messages and send replies directly through the bot.

Broadcast Messaging 📢: The ability to send a message to all groups in which the bot is currently an administrator.

Admin and Link Management: Tools to add or remove other bot administrators and manage promotional links used within the bot's messages.

---

## User Guide (User Workflow)

Start and Registration:

A user's journey begins by sending the /start command.

The bot first requires the user to join the main channel.

After confirming membership, the registration process starts, and the bot collects user information (contact, name, card, Sheba, bank) in a step-by-step manner.

Earning Rewards:

Once registration is complete, the user can start earning points by adding their friends and contacts to the specified groups.

The bot automatically and silently works in the background to detect new members, identify the user who added them, and credit their account with points.

Using the Main Menu:

The user can access all functionalities—such as viewing points, listing codes, requesting settlements, and contacting support—through the main menu's keyboard buttons.

All interactions are handled via predefined buttons for a simple and smooth user experience.

---

## Technical Overview: What Does This Bot Handle?

Data Management (Persistence):

All bot data is stored in a single JSON file named main_data.json. This approach eliminates dependencies on external database services and makes the project highly portable.

The bot features an automatic backup mechanism; if the JSON file becomes corrupted for any reason, the bot creates a backup of the faulty file and initializes a new, clean one to prevent a crash.

State and Conversation Management:

The bot extensively uses the powerful ConversationHandler module from the python-telegram-bot library to manage multi-step dialogues (like registration or editing information). This module ensures that the bot expects the correct input at each stage of a conversation and does not lose track of the user's progress.

Group and Member Management:

The bot automatically detects when it is added to a group, promoted to admin, or removed, and updates its database accordingly.

A scheduled task (JobQueue) periodically reviews and updates group information (e.g., a changed title) to ensure its data remains accurate.

The most critical piece of business logic, track_new_member, carefully verifies if a new member is truly "new" to the ecosystem, preventing duplicate point awards.

Error Handling:

A global ErrorHandler is defined for the bot. This means that if any part of the code encounters an unexpected error, the bot will not crash. Instead, it will log the error to the bot.log file and display a generic message to the user, informing them of the issue.

Asynchronous Operations:

The entire bot is built on asyncio. This architecture allows the bot to handle requests from a large number of users concurrently, ensuring it remains responsive and fast without getting blocked by any single operation.

---

## 🤝 Contributing

Contributions are welcome! Since this is a personal project, I appreciate any new ideas or improvements. Feel free to open an issue to discuss what you would like to change or submit a pull request.

---

## 📜 License

This project is licensed under the MIT License - see the `LICENSE` file for details.

---

## ✍️ Authors

This project was developed by **Komeyl Kalhorinia**. You can reach me at [komylfa@gmail.com](mailto:komylfa@gmail.com) for any inquiries.

---

<p align="center">
  Made with ❤️ by Komeyl Kalhorinia
</p>
