Quick Start
==========

Here are some common commands to get you started with autish:

Show current time and day
--------------------------

.. code-block:: bash

   autish tempo

Show time for UTC+9
--------------------

.. code-block:: bash

   autish tempo --horzono 9

Show time for all UTC offsets
------------------------------

.. code-block:: bash

   autish tempo --horzono

List Wi-Fi connections
-----------------------

.. code-block:: bash

   autish wifi ls

Connect to a network
---------------------

.. code-block:: bash

   autish wifi konekti "MyNetwork" -p "mypassword"

Show system info
-----------------

.. code-block:: bash

   autish sistemo

Run a command and copy its output to clipboard
----------------------------------------------

.. code-block:: bash

   autish kp echo "hello"

Copy the last captured kp output again (without re-running)
-----------------------------------------------------------

.. code-block:: bash

   autish kp

Getting Help
-------------

All commands provide built-in help:

.. code-block:: bash

   # View command help
   autish vorto --help

   # View subcommand help
   autish vorto aldoni --help

   # Read the man page
   cat docs/man/vorto.md

Command Reference
-----------------

For complete documentation of all 22 autish commands, see the
:doc:`commands/index` section.
