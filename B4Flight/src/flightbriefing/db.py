"""Contains the data classes (ORM Models) for the application 

Implements classes for:
    - User and UserSetting
    - NavPoint and NavPointCategory
    - FlightPlan and FlightPlanPoint
    - Briefing, Notam and QCode lookups
    
Provides command-line functions to:
    - Create the database models:  create-db
    - Import the CSV files containing QCode Lookups:  import-qcode-lookups
    - Import the CSV files contianing NavPoint Lookups:  import-navpoint-lookups 

"""

import os

from datetime import datetime, timedelta

from email.headerregistry import Address

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Date, Time, DateTime, Float, Text, ForeignKey, UniqueConstraint, and_
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from polycircles import polycircles

import jwt
import csv


from werkzeug.security import generate_password_hash

import click
from flask import current_app, render_template
from flask.cli import with_appcontext

from .data_handling import sqa_session
from . import helpers

#SQLAlchemny - A declarative base class  
Base = declarative_base() 

class User(Base):
    """
    A Class to respresent a B4Flight User
    
    Uses the SQLAlchemy ORM to interact with database
    
    Properties
    ----------
    Password
        returns hashed password
    
    Methods
    -------
    set_password(self, password)
        hashes and then sets the user password
        
    create_activation_token(self, expires_hrs=240)
        creates the Registration Activation token used to activate a user
        
    create_recovery_token(self, expires_hrs=24)
        creates a Password Recovery token

    activate_user(activation_token)
        Validates the activation token, and makes the user active
        
    """ 
    
    __tablename__ = 'Users'
    UserID = Column(Integer(), primary_key = True)
    Username = Column(String(50), nullable=False, unique=True)
    _password = Column("Password", String(1024), nullable=False)
    Firstname = Column(String(75))
    Lastname = Column(String(75))
    Email = Column(String(75), nullable=False, unique=True)
    Status_Pending = Column(Boolean(), default=True)
    Status_Active = Column(Boolean(), default=False)
    Access_Admin = Column(Boolean(), default=False)
    Create_Date = Column(DateTime(), default=datetime.utcnow)
    Activation_Mail_Date = Column(DateTime())
    Last_Login_Date = Column(DateTime())
    
    # Link to the FlightPlans Class, and UserSettings Class 
    FlightPlans = relationship("FlightPlan", back_populates="User")
    Settings = relationship("UserSetting", back_populates="User")
    HiddenNotams = relationship("UserHiddenNotam", back_populates="User")
    
    
    @hybrid_property
    def Password(self):
        return self._password

# This method did not always seem to work - therefore using the set_password method
#    @Password.setter
#    def Password(self, password):
#        self._password = generate_password_hash(password)
        
    def set_password(self, passwd):
        self._password = generate_password_hash(passwd)
    
    def create_activation_token(self, expires_hrs=240):
        """
        Creates an Activation Token, encoded using JWT (JSON Web Token),
        to be used by the user registration page to confirm user's e-mail address
        
        Parameters
        ----------
        expires_hrs : int, default=240
            expiry time for link in hours - not currently implemented
            
        Returns
        -------
        str
            The encoded token
        """
        
        expry = datetime.utcnow() + timedelta(hours=expires_hrs)
        expry = datetime.strftime(expry,"%Y-%m-%d %H:%M:%S")
        tkn = jwt.encode({'activate_user' : self.UserID, 'expires': expry}, current_app.config['SECRET_KEY'], 'HS256').decode('utf-8')
        return tkn

    def create_recovery_token(self, expires_hrs=24):
        """
        Creates a Password Recovery Token, encoded using JWT (JSON Web Token)
        
        Parameters
        ----------
        expires_hrs : int, default=24
            expiry time for link in hours
            
        Returns
        -------
        str
            The encoded token
        """
        
        expry = datetime.utcnow() + timedelta(hours=expires_hrs)
        expry = datetime.strftime(expry,"%Y-%m-%d %H:%M:%S")
        tkn = jwt.encode({'recover_user' : self.UserID, 'expires': expry}, current_app.config['SECRET_KEY'], 'HS256').decode('utf-8')
        return tkn

    @staticmethod
    def activate_user(activation_token):
        """
        Attempts to activate a newly-registered user, using the encoded activation token
        generated by create_activation_token and sent by e-mail
        
        Parameters
        ----------
        activation_token : str
            encoded activation token
            
        Returns
        -------
        One of:
            User
                an instance of User class, containing details of successfully activated user
            None
                if token is not valid
            -1
                if user has already been activated
        """
        # Attempt to decode the token. If decode fails, the token is not valid so return None
        try:
            usr_id = jwt.decode(activation_token, current_app.config['SECRET_KEY'], 'HS256')['activate_user']
        except:
            return None 

        # Retrieve the user
        sqa_sess = sqa_session()
        usr = sqa_sess.query(User).get(usr_id)
        
        # If user has been deleted
        if usr is None:
            return None
        
        # If user is not Pending - i.e. has been activated previously
        if usr.Status_Pending == False:
            return -1
        
        # Activate user and return user object
        usr.Status_Pending = False
        usr.Status_Active = True
        sqa_sess.commit()
        return usr

        
    @staticmethod
    def validate_recovery_token(recovery_token):
        """
        Validates whether the passed password recovery token is valid
        and if it is, return the userid.
        
        Parameters
        ----------
        recovery_token : str
            encoded password recovery token
            
        Returns
        -------
        One of:
            User
                an instance of User class
            None
                if token is not valid
            -1
                if token has expired
        """

        # Attempt to decode the token. If decode fails, the token is not valid so return None
        try:
            usr_id = jwt.decode(recovery_token, current_app.config['SECRET_KEY'], 'HS256')['recover_user']
            # Get the expiry date
            expiry = jwt.decode(recovery_token, current_app.config['SECRET_KEY'], 'HS256')['expires']
            # Convert expiry to a datetime and compare it to the current UTC time 
            expired = datetime.strptime(expiry,"%Y-%m-%d %H:%M:%S") < datetime.utcnow()
        except:
            current_app.logger.error(f'Error processing password recovery token')
            return None

        if expired == True:
            return -1
        
        # Retrieve the user
        sqa_sess = sqa_session()
        usr = sqa_sess.query(User).get(usr_id)
        
        # If user does not exist
        if usr is None:
            current_app.logger.error(f'Error retrieving user with ID: {usr_id}')
            return None
        
        # User is valid - so return the user
        return usr


class UserSetting(Base):
    """
    A Class to respresent a single Setting for a User
    
    Uses the SQLAlchemy ORM to interact with database
    
    Methods
    -------
    get_setting(user_id, setting_name, create_if_missing=True)
        Returns a UserSetting object for a specific user

    """ 
    __tablename__ = 'UserSettings'
    ID = Column(Integer(), primary_key=True)
    UserID = Column(Integer(), ForeignKey("Users.UserID"))
    SettingName = Column(String(128))
    SettingValue = Column(String(512))
    
    __table_args__ = (UniqueConstraint('UserID', 'SettingName'),)
    
    User = relationship("User")

    @staticmethod
    def get_setting(user_id, setting_name, create_if_missing=True):
        """
        Retrieves a UserSetting object for a specific setting for a specific user,
        and allows for the setting to be created if it doesn't yet exist.
        If the setting doesn't exist:
        - If create_if_missing ==  False, the application's DEFAULT_<<setting_name>> is returned
        - If create_if_missing ==  True, the application's DEFAULT_<<setting_name>> is returned and the setting is created
        
        
        Parameters
        ----------
        user_id : int
            The ID of the user to retrive the setting for
        setting_name : str
            The name of the setting to be retrieved.  If the setting doesn't exist, the DEFAULT value will be returned 
        create_if_missing : bool, default=True
            Specifies if the setting should be created for the user if it doesn't exist.
            Setting will be created from the app config variable DEFAULT_<<setting_name>>
            This allows new settings to be created in the app, without needing to update all users in the DB
            
        Returns
        -------
        UserSetting
            An instance of the UserSetting class, containing the setting.  Returning the object not the value,
            allows for the settings to be updated using this method
        """
        
        # Retrieve the setting
        sqa_sess = sqa_session()
        setg = sqa_sess.query(UserSetting).filter(and_(UserSetting.UserID ==  user_id, UserSetting.SettingName == setting_name)).first()
        
        # If this setting doesn't exist
        if setg is None:
            # Create a UserSetting object with the default value
            default_set = current_app.config['DEFAULT_'+setting_name.upper()]
            setg = UserSetting(UserID = user_id, SettingName = setting_name, SettingValue = default_set)
            
            # If method is asked to create the setting, then save to the DB
            if create_if_missing == True:
                sqa_sess.add(setg)
                sqa_sess.commit()
        
        return setg


class UserHiddenNotam(Base):
    """
    A Class to represent a Notam Number that a user has permanently hidden
    
    Uses the SQLAlchemy ORM to interact with database
    
    """ 
    __tablename__ = 'UserHiddenNotams'
    
    UserID = Column(Integer(), ForeignKey("Users.UserID"), primary_key= True)
    Notam_Number = Column(String(20), primary_key= True) #CAA-assigned Notam number - e.g. A1543/20
    Date_Hidden = Column(DateTime(), default=datetime.utcnow)
    
    User = relationship("User")


class NavPointCategory(Base):
    """
    A Class to respresent a Category for a NavPoint - eg. AD - Aerodrome / HS - Helistop / VOR / NDB etc.
    
    Uses the SQLAlchemy ORM to interact with database
    """

    __tablename__ = 'NavPointCategories'
    Category_Code = Column(String(10), primary_key = True)
    Description = Column(String(50))
    
    # Link this to the NavPoint Class 
    NavPoints = relationship("NavPoint", back_populates="Category")


class NavPoint(Base):
    """
    A Class to respresent a NavPoint - a named Navigation Point (eg. Aerodrome, VOR, Waypoint)
    Co-ordinates are in decimal degrees
    
    Uses the SQLAlchemy ORM to interact with database
    """

    __tablename__ = 'NavPoints'
    NavPointID = Column(Integer(), primary_key=True)
    Country_Code = Column(String(2))
    ICAO_Code = Column(String(50))
    Category_Code = Column(String(10), ForeignKey("NavPointCategories.Category_Code"))
    Description = Column(String(500))
    Latitude = Column(Float())
    Longitude = Column(Float())
    Active = Column(Boolean(), default=True)

    Category = relationship("NavPointCategory")


class FlightPlan(Base):
    """
    A Class to respresent a FlightPlan for a specific User.
    Contains the "header" details for the flightplan - the actual waypoints
    are contained in FlighPlanPoints in a one-to-many relationship
    
    Uses the SQLAlchemy ORM to interact with database
    """
    __tablename__ = 'FlightPlans'
    FlightplanID = Column(Integer(), primary_key=True)
    UserID = Column(Integer(), ForeignKey("Users.UserID"))
    Import_Date = Column(DateTime())
    File_Name = Column(String(255))
    Flight_Date = Column(Date())
    Flight_Name = Column(String(255))
    Flight_Desc = Column(String(255))
    Is_Deleted = Column(Boolean, default=False)
    
    # Link with the User (parent) and FlightPlanPoints (children)
    User = relationship("User")
    FlightPlanPoints = relationship("FlightPlanPoint", back_populates="FlightPlan")
    
    @property
    def Import_Date_Text(self):
        return self.Import_Date.strftime("%Y-%m-%d")


class FlightPlanPoint(Base):
    """
    A Class to respresent a single waypoint within a FlightPlan 
    Co-ordinates are in decimal degrees
    
    Uses the SQLAlchemy ORM to interact with database
    """
    __tablename__ = 'FlightPlanPoints'
    ID = Column(Integer(), primary_key=True)
    FlightplanID = Column(Integer(), ForeignKey("FlightPlans.FlightplanID"))
    Latitude = Column(Float())
    Longitude = Column(Float())
    Elevation = Column(Integer())
    Name = Column(String(255))
    
    # Relationship with the parent FlightPlan
    FlightPlan = relationship("FlightPlan", back_populates="FlightPlanPoints")




class QCode_2_3_Lookup(Base):
    """
    A Class to respresent the 2nd and 3rd letters of the NOTAM Q-Code 

    The Grouping attribute allows these codes to be grouped into categories, 
    used for filtering NOTAMS

    The Group_Colour attribute allows for colours to be assigned to the Q-Code,
    and used for display on the map
    
    Uses the SQLAlchemy ORM to interact with database
    """
    __tablename__ = "QCodes_2_3_Lookup"
    
    Code = Column(String(2), primary_key=True)
    Description = Column(String(512))
    Abbreviation = Column(String(50))
    Grouping = Column(String(50))
    Group_Colour = Column(String(50))
    
    # Links to a NOTAM
    Notams = relationship("Notam", back_populates="QCode_2_3_Lookup")


class QCode_4_5_Lookup(Base):
    """
    A Class to respresent the 4th and 5th letters of the NOTAM Q-Code 
    
    Uses the SQLAlchemy ORM to interact with database
    """
    __tablename__ = "QCodes_4_5_Lookup"
    
    Code = Column(String(2), primary_key=True)
    Description = Column(String(512))
    Abbreviation = Column(String(50))
    
    # Links to a NOTAM
    Notams = relationship("Notam", back_populates="QCode_4_5_Lookup")


class Briefing(Base):
    """
    A Class to respresent a daily CAA Briefing.  This is the "header", 
    and has a one-to-many relationship with NOTAMS
    
    Uses the SQLAlchemy ORM to interact with database
    """ 
    __tablename__ = "Briefings"
    
    BriefingID = Column(Integer, primary_key = True)
    Briefing_Country = Column(String(2)) #ICAO Country Code
    Briefing_Ref = Column(String(20)) #CAA-assigned Briefing Reference
    Briefing_Date = Column(Date) #Date CAA releases the briefing
    Briefing_Time = Column(Time) #Time CAA releases the briefing
    Import_DateTime = Column(DateTime) #Date & Time the briefing was imported
    
    Notams = relationship("Notam", back_populates='Briefing')


class Notam(Base):
    """
    A Class to respresent a single NOTAM, and is a child of 
    a Briefing 
    
    Uses the SQLAlchemy ORM to interact with database
    
    Methods
    -------
    is_circle
        Returns true if this NOTAM is a circle.  Used for mapping
        
    circle_bounded_area(self, number_vertices=32)
        Creates a Polygon representing a circle from a point + radius

    """ 
    
    __tablename__ = "Notams"
    
    NotamID = Column(Integer, primary_key=True) #Unique ID for each record
    BriefingID = Column(Integer, ForeignKey("Briefings.BriefingID"))
    Notam_Number = Column(String(20)) #CAA-assigned Notam number - e.g. A1543/20
    Notam_Series = Column(String(1)) #Notam Series - e.g. A/B/C/D
    Raw_Text = Column(Text) #The raw NOTAM text - primarily for troubleshooting
    FIR = Column(String(4)) #ICAO FIR Notam applies to
    Q_Code_2_3 = Column(String(2), ForeignKey("QCodes_2_3_Lookup.Code")) #Q-code letters 2+3 from the Q) field in Notam
    Q_Code_4_5 = Column(String(2), ForeignKey("QCodes_4_5_Lookup.Code")) #Q-code letters 4+5 from the Q) field in Notam
    Flightrule_Code = Column(String(4)) #Flightrule - I/V/K or combination
    Purpose_Code = Column(String(4)) #ICAO code describing the purpose of NOTAM 
    Scope_Code = Column(String(3)) #Scope of NOTAM - A(erodrome) / E(n-route) / W(Nav Warning) / K(Checklist)
    Scope_Aerodrome = Column(Boolean) #Is scope for Aerodrome?
    Scope_EnRoute = Column(Boolean) #Is Scope for En-Route?
    Scope_Nav_Warning = Column(Boolean) #Is scope for Nav Warning?
    Scope_Checklist = Column(Boolean) #Is scopt for Checklist?
    Q_Level_Lower = Column(String(10)) #Lower Level from Q Code
    Q_Level_Upper = Column(String(10)) #Upper Level from Q Code
    Q_Coord_Lat = Column(String(7)) #Latitude from Q Code
    Q_Coord_Lon = Column(String(8)) #Longitude from Q Code
    Radius = Column(Integer) #Radius from Q Code
    A_Location = Column(String(20)) #Locations from A) section of Notam
    From_Date = Column(DateTime) #Date Notam applies From - B) section of Notam
    To_Date = Column(DateTime) #Date Notam applies To - C) Section of Notam
    To_Date_Estimate = Column(Boolean) #Is the To Date an Estimated To Date?
    To_Date_Permanent = Column(Boolean) #Is the To Date Permanent?
    Notam_Text = Column(Text) #Text of the Notam - E) section of Notam
    Duration = Column(String(256)) #Duration of Notam - D) section of Notam
    Level_Lower = Column(String(15)) #Lower Level for Notam - combines F) section and Q) section
    Level_Upper = Column(String(15)) #Upper Level for Notam - combines G) section, Q) section E) Secion (text)
    E_Coord_Lat = Column(String(7)) #Co-ordinates extracted from the E) section (text)
    E_Coord_Lon = Column(String(8)) #Co-ordinates extracted from the E) section (text)
    Coord_Lat = Column(String(8)) #Final co-ordinates to use for the Notam Mapping
    Coord_Lon = Column(String(8)) #Final co-ordinates to use for the Notam Mapping
    Bounded_Area = Column(String(4096)) # Co-ordinates of a bounded area defined in the Notam
    Unique_Geo_ID = Column(String(25)) #Combination of Lat + Lon + Radius to allow grouping of 
        
    Briefing = relationship("Briefing", back_populates='Notams')
    QCode_2_3_Lookup = relationship("QCode_2_3_Lookup")
    QCode_4_5_Lookup = relationship("QCode_4_5_Lookup")
    
    def is_circle(self):
        """
        Is this NOTAM a circle?
        
        Returns
        -------
        bool
            Is this a circle
        """
        if self.Radius > 1 and self.Bounded_Area == '':
            return True
        else:
            return False


    def circle_bounded_area(self, number_vertices=32):
        """
        Creates a polygon representing a circle, using the centre co-ords of the NOTAM plus the radius
        Returns Co-ordinates in the same format that Bounded Areas are stored to allow this to be processed
        in the same way 
        
        Returns
        ------- 
        str
           a string of co-ordinates in format LAT,LON LAT,LON - in Degrees Minutes Seconds
        """
        
        radius_m = self.Radius * 1853 #convert radius from nautical miles to metres
        
        poly_coords = ''
        
        #create the circle
        polycircle = polycircles.Polycircle(latitude=helpers.convert_dms_to_dd(self.Coord_Lat), longitude=helpers.convert_dms_to_dd(self.Coord_Lon), radius=radius_m, number_of_vertices=number_vertices)
        circ_coords = polycircle.to_lat_lon()

        #convert circle's decimal degree lat,lon tuples into DMS and convert to string in same format as bounded area (i.e. LAT,LON LAT,LON)
        for coord in circ_coords:
            lat, lon = helpers.convert_dd_to_dms(coord[0], coord[1])
            poly_coords += f'{lat},{lon} '
            
        return poly_coords.strip()


class ContactMessage(Base):
    """
    A Class to respresent a message received from a User
    
    Uses the SQLAlchemy ORM to interact with database
    
    """ 
    __tablename__ = 'ContactMessages'
    ID = Column(Integer(), primary_key=True)
    UserID = Column(Integer(), ForeignKey("Users.UserID"))
    Firstname = Column(String(75))
    Email = Column(String(75), nullable=False)
    Message = Column(String(500), nullable=False)
    Status_Pending = Column(Boolean(), default=True)
    Status_Closed = Column(Boolean(), default=False)
    Create_Date = Column(DateTime(), default=datetime.utcnow)
    
    User = relationship("User")

    @staticmethod
    def send_message(firstname, email_address, message, user_id=None):
        """
        Sends a Message to the administrator, and stores the message in the table.

        Parameters
        ----------
        firstname : str
            The first name of the person sending the message
        email_address : str
            The email address of the person sending the message
        message : str
            The message that was sent
        user_id : int, optional
            The userID of the user who sent the message - if this is a registered user
            
        Returns
        -------
        bool
            Was the email successfully sent?
        ContactMessage
            An instance of the ContactMessage class, containing the message
        """
        
        # Retrieve the setting
        sqa_sess = sqa_session()
        
        msg = ContactMessage(Firstname = firstname, Email = email_address, Message = message)
        if user_id:
            msg.UserID = user_id
        
        sqa_sess.add(msg)
        sqa_sess.commit()
        
        msg_txt = render_template('emails/contactus_email.txt', firstname=firstname, message=message)
        msg_html = render_template('emails/contactus_email.html', firstname=firstname, message=message)
        
        mail_to = Address(display_name = firstname, addr_spec = email_address)
        mail_from = Address(display_name = current_app.config['EMAIL_ADMIN_NAME'], addr_spec = current_app.config['EMAIL_ADMIN_ADDRESS'])
        mail_bcc = Address(display_name = current_app.config['EMAIL_ADMIN_NAME'], addr_spec = current_app.config['EMAIL_CONTACTUS_ADDRESS']) 
        was_mail_sent = helpers.send_mail(mail_from, mail_to,'Thank you for contacting us.', msg_txt, msg_html, recipients_bcc=mail_bcc)
        
        return was_mail_sent, msg
        
    
def init_db(sqa_engine):
    """Initialise the SQLAlchemy database - for use when DB module is used
    on a standalone basis, without the SQLAlchemy connectivity in the app 
    
    Parameters
    ----------
    sqa_engine : sqlalchemy.engine
        SQLAlchemy database engine
        
    """ 

    #The declarative Base is bound to the database engine.
    Base.metadata.bind = sqa_engine


def create_new_db():
    """Creates / updates the underlying database tables from the SQLAlchemydatabase ORM model, 
    using SQLAlchemy "reflection" to create the tables
    """ 

    sqa_engine = create_engine(current_app.config['DATABASE_CONNECT_STRING'], pool_recycle = current_app.config['DATABASE_POOL_RECYCLE'])

    #Create defined tables
    Base.metadata.bind = sqa_engine
    Base.metadata.create_all()


def import_qcode_ref_tables(csv_script_folder):
    """Imports CSV files containing the Q_Code lookup data, 
    into the underlying tables for Q_Code_2_3_Lookup and Q_Code_4_5_Lookup objects
    
    Typically would be run from the command-line using "flask"
    
    Specific filenames are required - Q_Code_2_3.csv and Q_Code_4_5.csv
    CSV Files must be UTF-8 encoded
    
    Parameters
    ----------
    csv_script_folder: str
        folder containing the CSV files Q_Code_2_3.csv and Q_Code_4_5.csv
        
    """ 
    
    q_code_file1 = os.path.join(csv_script_folder, 'Q_Code_2_3.csv')
    q_code_file2 = os.path.join(csv_script_folder, 'Q_Code_4_5.csv')
    
    print('--- Preparing to import Q_Code Lookup files ---')

    # Check the files and folders exist
    if not os.path.exists(csv_script_folder):
        print(f'***Error*** CSV Script Folder does not exist: {csv_script_folder}')
        return False
    
    if not os.path.isfile(q_code_file1):
        print(f'***Error*** CSV File does not exist: {q_code_file1}')
        return False
        
    if not os.path.isfile(q_code_file2):
        print(f'***Error*** CSV File does not exist: {q_code_file2}')
        return False
        
    # Create the SQL_Alchemy session
    ses = sqa_session()

    # Import QCode 2_3
    row_count = 0
    with open(q_code_file1) as imp_file:
        csv_reader = csv.DictReader(imp_file)
        for row in csv_reader:
            ref = QCode_2_3_Lookup(Code = row['Code'], Description = row['Description'], 
                                   Abbreviation = row['Abbreviation'], Grouping = row['Grouping'], Group_Colour = row['Group_Colour'])
            # Add to the session
            ses.add(ref)
            # Increase row count
            row_count += 1

    print(' - Imported QCode Lookups: QCode_2_3_Lookup, {row_count} rows')

    # Import QCode 4_5
    row_count = 0
    with open(q_code_file2) as imp_file:
        csv_reader = csv.DictReader(imp_file)
        for row in csv_reader:
            ref = QCode_4_5_Lookup(Code = row['Code'], Description = row['Description'], Abbreviation = row['Abbreviation'])

            # Add to the session
            ses.add(ref)
            # Increase row count
            row_count += 1

    print(' - Imported QCode Lookups: QCode_4_5_Lookup, {row_count} rows')
    
    # Commit to the DB
    ses.commit()
    print('--- Imprt Successful.  Job Completed---')



def import_navpoint_ref_tables(csv_script_folder):
    """Imports CSV files containing the NavPoint and NavPointCategory lookup data, 
    into the underlying tables for NavPoint and NavPointCategory objects
    
    Typically would be run from the command-line using "flask"
    
    Specific filenames are required - NavPoint_Category.csv and NavPoints.csv
    CSV Files must be UTF-8 encoded
    
    Parameters
    ----------
    csv_script_folder: str
        folder containing the CSV files NavPoint_Category.csv and NavPoints.csv
        
    """ 

    point_file = os.path.join(csv_script_folder, 'NavPoints.csv')
    category_file = os.path.join(csv_script_folder, 'NavPoint_Category.csv')
    
    print('--- Preparing to import NavPoint Lookup files ---')

    # Check the files and folders exist
    if not os.path.exists(csv_script_folder):
        print(f'***Error*** CSV Script Folder does not exist: {csv_script_folder}')
        return False
    
    if not os.path.isfile(category_file):
        print(f'***Error*** CSV File does not exist: {category_file}')
        return False
        
    if not os.path.isfile(point_file):
        print(f'***Error*** CSV File does not exist: {point_file}')
        return False
        
    # Create the SQL_Alchemy session
    ses = sqa_session()
    
    # Import the Category File
    row_count = 0
    with open(category_file) as imp_file:
        csv_reader = csv.DictReader(imp_file)
        for row in csv_reader:
            ref = NavPointCategory(Category_Code = row['Category_Code'], Description = row['Description'])
            ses.add(ref)
            # Increase row count
            row_count += 1
    
    print(' - Imported NavPoint Category File, {row_count} rows')
    
    # Import NavPoint file
    row_count = 0
    with open(point_file) as imp_file:
        csv_reader = csv.DictReader(imp_file)
        for row in csv_reader:
            ref = NavPoint(Country_Code = row['Country_Code'], ICAO_Code = row['ICAO_Code'],
                            Category_Code = row['Category_Code'], Description = row['Description'],
                            Latitude = row['Latitude'], Longitude = row['Longitude'])
            ses.add(ref)
            # Increase row count
            row_count += 1
    
    print(' - Imported NavPoints File, {row_count} rows')
    
    # Commit to the DB
    ses.commit()
    print('--- Imprt Successful.  Job Completed---')


def create_admin_user(admin_email, admin_user='b4admin', admin_pass='b4admin'):
    """Create an Admin User 
    
    Typically would be run from the command-line using "flask"
    
    Parameters
    ----------
    admin_email : str
        Admin's email address
    admin_user : str, default = 'b4admin'
        Admin username
    admin_password : str, default = 'b4admin'
        Admin password (will be hashed when stored in DB)
        
    """ 

    print('--- Preparing to create admin user ---')
    
    ses = sqa_session()
    
    new_admin = User()
    new_admin.Username = admin_user
    new_admin.Password = admin_pass
    new_admin.Email = admin_email
    new_admin.Status_Active = True
    new_admin.Status_Pending = False
    new_admin.Access_Admin = True 

    ses.add(new_admin)
    ses.commit()

    print('--- Admin User Added ---')


@click.command('create-db')
@with_appcontext
def create_db_command():
    """Command-line to create the B4Flight Databases
    usage: flask create-db
    
    Parameters
    ----------
    None
    
    """
    click.echo("--- Command-Line ready to create the core B4Flight databases ---")
    create_new_db()
    click.echo("--- Command-Line Completed ---")

    
@click.command('import-qcode-lookups')
@click.argument('csv_folder')
@with_appcontext
def import_qcode_lookup_command(csv_folder):
    """Command-Line to import the Q-Code lookup CSV Files.
    Must be named Q_Code_2_3.csv and Q_Code_4_5.csv. Encoding UTF8
    usage: flask import-qcode-lookups <<csv_foler>>
    
    Parameters
    ----------
    csv_folder : str
        Folder that the required CSV files are stored in
    """
    
    click.echo("--- Command-Line ready to import QCode lookup files ---")
    
    import_qcode_ref_tables(csv_folder)
    
    click.echo("--- Command-Line Completed ---")


@click.command('import-navpoint-lookups')
@click.argument('csv_folder')
@with_appcontext
def import_navpoint_lookup_command(csv_folder):
    """Command-Line to import the Q-Code lookup CSV Files.
    Must be named Navpoint_Category.csv and Navpoints.csv. Encoding UTF8
    usage: flask import-navpoint-lookups <<csv_foler>>
    
    Parameters
    ----------
    csv_folder : str
        Folder that the required CSV files are stored in
    """
    
    click.echo("--- Command-Line ready to import NavPoint lookup files ---")
    
    import_navpoint_ref_tables(csv_folder)

    click.echo("--- Command-Line Completed ---")


def init_app(app):
    """
    Register the Command-Line commands with the flightbriefing app
    """
    
    app.cli.add_command(create_db_command)
    app.cli.add_command(import_qcode_lookup_command)
    app.cli.add_command(import_navpoint_lookup_command)
    
