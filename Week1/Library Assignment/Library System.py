
class Library:
    def __init__(self):
        """Initializes the library with empty members and books dictionaries, and a member ID counter starting at 0."""
        self.member_id_counter = 0
        self.members = {}
        self.books = {}

    
    def add_book(self):
        """Prompts the user for book details and adds the book to the library. If the book ID already exists, increments its available copy count instead."""
        title = input("Book title: ").strip()
        book_id = input("Book ID: ").strip()
        author = input("Author: ").strip()
        if book_id in self.books:
            self.books[book_id]["available_copies"] += 1
        else:
            self.books[book_id] = {"title": title, "author": author, "available_copies": 1}
        print("Book successfully added!")
            
    def add_member(self):
        """Prompts for a member's name, registers them with an auto-incremented ID, and initializes their issued books as an empty set."""
        name = str(input("What is your name")).strip()
        self.members[self.member_id_counter] = {"name":name, "issued_book": set()}
        print(f"Member successfully added! Your member ID is: {self.member_id_counter}")
        self.member_id_counter += 1
        return

    def view_all_members(self):
        """Prints all registered members along with their IDs and the titles of any books they currently have issued."""
        if not self.members:
            print("No members registered!")
            return
        print("List of all members:")
        for id, member in self.members.items():
            books = ", ".join(self.books[book_id]["title"] for book_id in member["issued_book"]) \
            if member["issued_book"] else "No assigned books!"
            print(f'Name: {member["name"]}, ID: {id}, Books owned: {books}')
    
    def view_all_books(self):
        """Prints all books in the library including their title, author, book ID, and number of available copies."""
        if not self.books:
            print("There are currently no books in the library!")
            return
        print("List of all books")
        for ID, book in self.books.items():
            print(f'Title: {book["title"]}, Author: {book["author"]}, Book ID: {ID} Copies: {book["available_copies"]}' )
        return
    
    def issue_book(self):
        """Prompts for a member ID and book ID, then issues the book to the member if both exist and a copy is available."""
        member_id = int(str(input("What is your member ID:")).strip())
        book_id = str(input("What is the book ID you would like to take out:")).strip()
        if member_id not in self.members:
            print("Member ID doesn't exist!")
            return
        if book_id in self.books and self.books[book_id]["available_copies"] > 0:
            self.members[member_id]["issued_book"].add(book_id)
            self.books[book_id]["available_copies"] -= 1
            print("Book has been successfully issued to:", self.members[member_id]["name"])
        else:
            print("Book id is not found or available!")
        return
    
    def return_book(self):
        """Prompts for a member ID and book ID, then returns the book if the member currently has it issued, restoring one available copy."""
        member_id = int(str(input("What is your member ID:")).strip())
        book_id = str(input("What is the book ID you would like to return:")).strip()
        if member_id not in self.members:
            print("Member ID doesn't exist!")
            return
        if book_id not in self.members[member_id]["issued_book"]:
            print("You do not own this book to return it!")
            return
        if book_id in self.books:
            self.books[book_id]["available_copies"] += 1
            self.members[member_id]["issued_book"].remove(book_id)
            print("Book Successfully added!")
        else:
            print("Please issue this book to our inventory first!")
        
        return
    
    def searche_book(self, book_title):
        """Searches for a book by exact title and prints its ID, author, and available copies if found."""
        for id, book in self.books.items():
            if book["title"] == book_title:
                print(f'Book id: {id}, Book Name: {book_title}, Author: {book["author"] } Available Copies: {book["available_copies"]}')
    

    
Prince = Library()

while True:
    try:
        num = int(input(
            "\nWhat would you like to do today:"
            "\n 1. Add book"
            "\n 2. View all books"
            "\n 3. Add member"
            "\n 4. View all members"
            "\n 5. Issue book"
            "\n 6. Return book"
            "\n 7. Search book"
            "\n 8. Exit"
            "\n> "
        ))
    except ValueError:
        print("Please enter a number between 1 and 8.")
        continue

    if num == 1:
        Prince.add_book()
    elif num == 2:
        Prince.view_all_books()
    elif num == 3:
        Prince.add_member()
    elif num == 4:
        Prince.view_all_members()
    elif num == 5:
        Prince.issue_book()
    elif num == 6:
        Prince.return_book()
    elif num == 7:
        title = input("Book title to search: ").strip()
        Prince.searche_book(title)
    elif num == 8:
        print("Goodbye!")
        break
    else:
        print("Invalid option, please choose 1-8.")

