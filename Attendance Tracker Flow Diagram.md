# Attendance Tracker Flow Diagram

## Admin User

*Roles and access for admin user*

1. Login: Password, Username, 2FA (Using Authenticator App OTP)

2. Add Volunteer Accounts

3. Change or Add Programs Kid's Can Be Checked In to

4. Download and View Attendance Statistics and CSVs.

5. Change Registration Fields needed for new kids to be registered.

6. View Each registered Childs QR Code and download a generated ChildName&SurnameQR.jpg incase parents loose it.

## Volunteer User

*Roles and access for volunteer user*

1. Login: Password, Username, 2FA (Using Authenticator App OTP)

2. Register New Children

3. Scan and Check in New Children.

## Scanner Screen:

1. Live Search Bar: Search a child by name or surname. (every letter type should refresh the results below the search to see matches in database) --> If Child is checked in through the search bar, in the check in modal or screen have a tick box to resend ChildName&SurnameQR.jpg and then when child is checked in also attach the QR jpg to the message.

2. QR Code Scanner

3. Button to 'Register New Child'

## Registration Screen

Fields to register new child:

##### Parent/Guardian Information

**First Name**: [Text Input]* 

**Last Name:** [Text Input]*

**Phone Number:** Needs 10 Numbers (only 10)* 

**Email:** [Validation: Needs a @ and a . after that]* 

**Relationship** [Dropdown: Mother, Father, Guardian, Grandparent, Sibling, Aunt/Uncle]* 

##### Child Information

**First Name**: [Text Input]*

**Last Name:** [Text Input]*

**Birthdate** [Dropdowns for: Year, Month, Day]*

**Medical Notes:** [Text Input with prompt text: List any allergies, current medications or other relevant medical information]

**Special Instructions:** [Text Input]

**Program:** [Dropdown: Selection from Admin User's Programs]



**Button:** [Cancel Registration]

**Button:** [Register Child]



### When Child is Registered

1. Add to database

2. Check Child in

3. Future: Send whatsapp/email to inform parent child is registered and checked in and attach generated ChildName&SurnameQR.jpg

### When Child is Checked In

1. Check Child in on database

2. Future: Send whatsapp/email to inform parent child is  checked in.






